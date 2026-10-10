import math
import time
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MAX_URLS = 3
MAX_MINUTES = 60
PAGE_TIMEOUT_MS = 15000
DELAY_SECONDS = 2.0
USER_AGENT = "SiteTestingBot/1.0"


def normalize_url(raw):
    raw = raw.strip()
    if not urlparse(raw).scheme:
        raw = "https://" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Enter a valid HTTP or HTTPS URL.")

    return raw


def ask_minutes(url):
    while True:
        try:
            minutes = float(input(
                f"Run browser testing on {url} for how many minutes (max 60)? "
            ))
            if not math.isfinite(minutes) or not 0 < minutes <= MAX_MINUTES:
                raise ValueError
            return minutes
        except ValueError:
            print("Enter a number greater than 0 and no more than 60.")


def crawl(browser, start_url, minutes):
    parsed_start = urlparse(start_url)
    allowed_host = (parsed_start.hostname or "").lower()
    deadline = time.monotonic() + minutes * 60

    queue = deque([start_url])
    seen = {start_url}
    visited = 0
    errors = 0

    context = browser.new_context(user_agent=USER_AGENT)

    # Permit normal page resources, but block navigation to other hosts.
    def guard_navigation(route):
        request = route.request

        if request.is_navigation_request():
            target_host = (urlparse(request.url).hostname or "").lower()
            if target_host != allowed_host:
                route.abort()
                return

        route.continue_()

    context.route("**/*", guard_navigation)
    page = context.new_page()
    page.set_default_navigation_timeout(PAGE_TIMEOUT_MS)

    # Prevent JavaScript popups from opening extra tabs.
    page.on("popup", lambda popup: popup.close())

    print(f"\nStarting: {start_url}")
    print(f"Duration: {minutes} minute(s)")
    print(f"Allowed host: {allowed_host}")

    try:
        while time.monotonic() < deadline:
            if not queue:
                # No undiscovered pages remain.
                break

            url = queue.popleft()

            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=PAGE_TIMEOUT_MS,
                )
                visited += 1

                status = response.status if response else "unknown"
                print(f"[{status}] {url}")

                # Discover links only if the final page stayed on-site.
                final_url = page.url
                final_host = (urlparse(final_url).hostname or "").lower()

                if final_host != allowed_host:
                    print(f"[BLOCKED] Unexpected destination: {final_url}")
                    continue

                links = page.locator("a[href]").evaluate_all(
                    "(elements) => elements.map(a => a.href)"
                )

                for href in links:
                    absolute, _ = urldefrag(urljoin(final_url, href))
                    parsed = urlparse(absolute)

                    if (
                        parsed.scheme in ("http", "https")
                        and (parsed.hostname or "").lower() == allowed_host
                        and absolute not in seen
                    ):
                        seen.add(absolute)
                        queue.append(absolute)

            except PlaywrightTimeoutError:
                errors += 1
                print(f"[TIMEOUT] {url}")

            except Exception as exc:
                errors += 1
                print(f"[ERROR] {url}: {exc}")

            # Keep the request rate conservative.
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(DELAY_SECONDS, remaining))

    finally:
        context.close()

    print(
        f"Finished {start_url}: {visited} page visits, "
        f"{errors} errors, {len(seen)} unique URLs discovered."
    )


def main():
    urls = []

    print(f"Enter up to {MAX_URLS} website URLs.")
    print("Press Enter on an empty line to finish.")

    while len(urls) < MAX_URLS:
        raw = input(f"URL {len(urls) + 1}: ").strip()

        if not raw:
            if urls:
                break
            print("Enter at least one URL.")
            continue

        try:
            urls.append(normalize_url(raw))
        except ValueError as exc:
            print(exc)

    if not urls:
        return

    plan = [(url, ask_minutes(url)) for url in urls]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            for url, minutes in plan:
                crawl(browser, url, minutes)
        except KeyboardInterrupt:
            print("\nStopped by user.")
        finally:
            browser.close()

    print("All done.")


if __name__ == "__main__":
    main()
