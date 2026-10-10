#!/usr/bin/env python3
"""
Sequential traffic generator.

- Accepts up to 3 URLs, crawled one after another (never at the same time).
- Asks how many minutes to crawl each URL.
- Stays on the same domain as the starting URL, following links it finds.
- Single-threaded with a delay between requests, so it behaves like one
  polite visitor rather than a flood.

Only use this on sites you own or have permission to test.

Requires: pip install requests
"""
#begin!
import random
import time
import sys
from collections import deque
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag

import requests

MAX_URLS = 3
REQUEST_DELAY_SECONDS = 1.0  # pause between requests
REQUEST_TIMEOUT_SECONDS = 10
USER_AGENT = "TrafficCrawler/1.0 (site testing script)"


class LinkParser(HTMLParser):
    """Collects href values from <a> tags."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


def normalize(url: str) -> str:
    """Add a scheme if missing."""
    url = url.strip()
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def is_valid_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def ask_urls() -> list[str]:
    print(f"Enter up to {MAX_URLS} URLs to crawl (press Enter on an empty line to finish).")
    urls = []
    while len(urls) < MAX_URLS:
        raw = input(f"URL {len(urls) + 1}: ").strip()
        if not raw:
            if urls:
                break
            print("Please enter at least one URL.")
            continue
        url = normalize(raw)
        if not is_valid_http_url(url):
            print("  That doesn't look like a valid URL, try again.")
            continue
        urls.append(url)
    return urls


def ask_minutes(url: str) -> float:
    while True:
        raw = input(f"How many minutes should I crawl {url}? ").strip()
        try:
            minutes = float(raw)
            if minutes <= 0:
                raise ValueError
            return minutes
        except ValueError:
            print("  Please enter a positive number (e.g. 5 or 0.5).")


def crawl(start_url: str, minutes: float, session: requests.Session) -> None:
    domain = urlparse(start_url).netloc
    end_time = time.time() + minutes * 60

    queue = deque([start_url])
    seen = {start_url}
    visited = 0
    errors = 0

    print(f"\n=== Crawling {start_url} for {minutes} minute(s) ===")

    while time.time() < end_time:
        if not queue:
            # Ran out of new links; start over from the beginning of the site.
            queue.append(start_url)

        url = queue.popleft()

        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            visited += 1
            remaining = max(0, int(end_time - time.time()))
            print(f"[{response.status_code}] {url}  (requests: {visited}, {remaining}s left)")

            content_type = response.headers.get("Content-Type", "")
            if response.ok and "text/html" in content_type:
                parser = LinkParser()
                parser.feed(response.text)
                new_links = []
                for href in parser.links:
                    absolute, _ = urldefrag(urljoin(url, href))
                    if (
                        is_valid_http_url(absolute)
                        and urlparse(absolute).netloc == domain
                        and absolute not in seen
                    ):
                        seen.add(absolute)
                        new_links.append(absolute)
                random.shuffle(new_links)
                queue.extend(new_links)
        except requests.RequestException as exc:
            errors += 1
            print(f"[ERR] {url}: {exc}")

        # Sleep, but never past the end time
        sleep_for = min(REQUEST_DELAY_SECONDS, max(0, end_time - time.time()))
        time.sleep(sleep_for)

    print(f"Finished {start_url}: {visited} requests, {errors} errors, {len(seen)} unique pages found.")


def main() -> None:
    urls = ask_urls()

    # Ask for each URL's duration so the crawl can run unattended.
    plan = [(url, ask_minutes(url)) for url in urls]

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    try:
        for url, minutes in plan:
            crawl(url, minutes, session)
    except KeyboardInterrupt:
        print("\nStopped by user.")
        sys.exit(0)

    print("\nAll done.")


if __name__ == "__main__":
    main()
