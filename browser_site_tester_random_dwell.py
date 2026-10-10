import math
import random
import time
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MAX_URLS = 3
MAX_MINUTES = 60
PAGE_TIMEOUT_MS = 15000
MIN_DWELL_SECONDS = 10
MAX_DWELL_SECONDS = 5 * 60
USER_AGENT = "AuthorizedSiteUsabilityTest/1.0 (Playwright automation)"


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


def wait_until_or_deadline(seconds, deadline):
    """Wait for a page dwell interval without intentionally passing the run deadline."""
    end = min(time.monotonic() + seconds, deadline)
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def crawl(browser, start_url, minutes):
    parsed_start = urlparse(start_url)
    allowed_host = (parsed_start.hostname or "").lower()
    deadline = time.monotonic() + minutes * 60

    queue = deque([start_url])
    seen = {start_url}
    visited = 0
    errors = 0

    context = browser.new_context(user_agent=USER_AGENT)

    # Keep browser navigations on the starting hostname.
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
    page.on("popup", lambda popup: popup.close())

    print(f"\nStarting: {start_url}")
    print(f"Run duration: {minutes} minute(s), maximum {MAX_MINUTES}")
    print(f"Allowed hostname: {allowed_host}")
    print(
        f"Random page dwell: {MIN_DWELL_SECONDS}–"
        f"{MAX_DWELL_SECONDS} seconds (automation is identified in the user-agent)."
    )

    # If no undiscovered links remain, revisit known same-site pages until the
    # deadline so the requested run duration remains meaningful.
    known_pages = [start_url]

    try:
        while time.monotonic() < deadline:
            if queue:
                url = queue.popleft()
            else:
                url = random.choice(known_pages)

            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            if remaining_ms <= 1:
                break

            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=min(PAGE_TIMEOUT_MS, remaining_ms),
                )
                visited += 1
                status = response.status if response else "unknown"
                print(f"[{status}] {url}")

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
                        known_pages.append(absolute)
                        queue.append(absolute)

                # Remain on this page for a randomly selected interval.
                dwell = random.uniform(MIN_DWELL_SECONDS, MAX_DWELL_SECONDS)
                actual_dwell = min(dwell, max(0, deadline - time.monotonic()))
                print(f"  Staying on page for {actual_dwell:.1f} seconds.")
                wait_until_or_deadline(actual_dwell, deadline)

            except PlaywrightTimeoutError:
                errors += 1
                print(f"[TIMEOUT] {url}")
            except Exception as exc:
                errors += 1
                print(f"[ERROR] {url}: {exc}")

    finally:
        context.close()

    print(
        f"Finished {start_url}: {visited} page visits, "
        f"{errors} errors, {len(seen)} unique URLs discovered."
    )


def main():
    urls = []
    print(f"Enter up to {MAX_URLS} website URLs you are authorized to test.")
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
