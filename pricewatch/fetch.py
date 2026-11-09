"""Polite access to the web: robots.txt, a generic user agent, a pause between requests and retries.

PoliteClient serves both collection methods: requests for static pages, and the robots/pace checks
that the Selenium collector calls before each navigation or click.
"""
from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from .config import DELAY_SECONDS, RETRIES, TIMEOUT_SECONDS, USER_AGENT


class Disallowed(Exception):
    """The site's robots.txt does not allow this URL for our user agent."""


class PoliteClient:
    def __init__(self, user_agent: str = USER_AGENT, delay: float = DELAY_SECONDS, retries: int = RETRIES,
                 timeout: float = TIMEOUT_SECONDS, backoff: float = 2.0):
        self.user_agent, self.delay, self.retries, self.timeout, self.backoff = (
            user_agent, delay, retries, timeout, backoff)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.robots: dict[str, RobotFileParser] = {}
        self._last_call: dict[str, float] = {}
        self.requests_made = 0

    # ------------------------------------------------------------------ robots.txt
    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            rp = RobotFileParser(f"{origin}/robots.txt")
            try:
                resp = self.session.get(rp.url, timeout=self.timeout)
                if resp.status_code in (401, 403) or resp.status_code >= 500:
                    rp.disallow_all = True       # access denied or unknown: assume nothing is allowed
                elif resp.status_code >= 400:
                    rp.allow_all = True          # no robots.txt (404): nothing is disallowed
                else:
                    rp.parse(resp.text.splitlines())
            except requests.RequestException:
                rp.disallow_all = True
            self.robots[origin] = rp
        return self.robots[origin]

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------ pace
    def wait(self, url: str) -> None:
        """Sleep until the minimum gap since the last request to this site has passed."""
        host = urlsplit(url).netloc
        crawl_delay = self._robots_for(url).crawl_delay(self.user_agent) or 0
        gap = max(self.delay, float(crawl_delay))
        elapsed = time.monotonic() - self._last_call.get(host, float("-inf"))
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_call[host] = time.monotonic()

    # ------------------------------------------------------------------ static pages
    def get(self, url: str) -> str:
        if not self.allowed(url):
            raise Disallowed(url)
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.wait(url)
            self.requests_made += 1
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:  # timeout, DNS, connection reset
                last_error = exc
            else:
                if resp.status_code == 200:
                    if "charset" not in resp.headers.get("Content-Type", "").lower():
                        resp.encoding = resp.apparent_encoding  # else requests assumes Latin-1 and '£' becomes 'Â£'
                    return resp.text
                last_error = requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                if resp.status_code != 429 and resp.status_code < 500:
                    break  # 404, 410...: retrying will not help
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    time.sleep(min(int(retry_after), 60))
            if attempt < self.retries:
                time.sleep(self.backoff * attempt)
        raise last_error or RuntimeError(url)


# --------------------------------------------------------------------------- dynamic pages
@contextmanager
def open_browser(user_agent: str = USER_AGENT) -> Iterator["webdriver.Chrome"]:  # noqa: F821
    """Headless Chrome with the same generic user agent. Selenium Manager fetches the matching driver."""
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1366,900")
    options.add_argument(f"--user-agent={user_agent}")
    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        driver.quit()
