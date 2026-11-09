"""Polite HTTP: robots.txt first, a generic user agent, a pause between requests, retries that make sense."""
from __future__ import annotations

import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from .config import DELAY_SECONDS, RETRIES, TIMEOUT_SECONDS, USER_AGENT


class FetchError(Exception):
    """The page could not be loaded. `reason` is what goes into the coverage report."""

    def __init__(self, reason: str, http_status: int | None = None, attempts: int = 1):
        super().__init__(reason)
        self.reason, self.http_status, self.attempts = reason, http_status, attempts


class PoliteClient:
    def __init__(self, user_agent: str = USER_AGENT, delay: float = DELAY_SECONDS, retries: int = RETRIES,
                 timeout: float = TIMEOUT_SECONDS, backoff: float = 2.0, session=None):
        self.user_agent, self.delay, self.retries, self.timeout, self.backoff = (
            user_agent, delay, retries, timeout, backoff)
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.robots: dict[str, RobotFileParser] = {}
        self.robots_note: dict[str, str] = {}  # what robots.txt said, for the report
        self._last_call = float("-inf")
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
                    rp.disallow_all = True
                    note = f"unreadable (HTTP {resp.status_code}): nothing crawled"
                elif resp.status_code >= 400:
                    rp.allow_all = True
                    note = f"none published (HTTP {resp.status_code}): nothing disallowed"
                else:
                    rp.parse(resp.text.splitlines())
                    note = "read and obeyed"
            except requests.RequestException:
                rp.disallow_all = True
                note = "unreachable: nothing crawled"
            self.robots[origin], self.robots_note[origin] = rp, note
        return self.robots[origin]

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).can_fetch(self.user_agent, url)

    def _wait(self, url: str) -> None:
        crawl_delay = self._robots_for(url).crawl_delay(self.user_agent) or 0
        gap = max(self.delay, float(crawl_delay))
        elapsed = time.monotonic() - self._last_call
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_call = time.monotonic()

    # ------------------------------------------------------------------ pages
    def get(self, url: str) -> tuple[str, int]:
        """Return (html, attempts). Raise FetchError with a short, reportable reason."""
        reason, status = "unknown error", None
        for attempt in range(1, self.retries + 1):
            self._wait(url)
            self.requests_made += 1
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.Timeout:
                reason, status = "timeout", None
            except requests.RequestException as exc:
                reason, status = f"connection error ({type(exc).__name__})", None
            else:
                if resp.status_code == 200:
                    if "charset" not in resp.headers.get("Content-Type", "").lower():
                        resp.encoding = resp.apparent_encoding  # else '£' arrives as 'Â£'
                    return resp.text, attempt
                reason, status = f"HTTP {resp.status_code}", resp.status_code
                if resp.status_code != 429 and resp.status_code < 500:
                    raise FetchError(reason, status, attempt)  # 404, 410...: retrying will not help
            if attempt < self.retries:
                time.sleep(self.backoff * attempt)
        raise FetchError(f"{reason} after {self.retries} attempts", status, self.retries)
