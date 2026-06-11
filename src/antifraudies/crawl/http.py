"""HTTP client for the crawler.

The goal is to scrape a very large catalog quickly — many requests in flight, no fixed
delay between them — while staying defensible:
  - Identify honestly: a truthful User-Agent token plus a contact address.
  - Send realistic Accept / Accept-Language headers (the target's Akamai edge requires
    them) without disguising our identity in the UA token.
  - Back off on pushback: exponential backoff with jitter on 429 / 5xx / transport errors.
    Being fast is not the same as being abusive — if the server signals stress, we yield.

Concurrency is driven by the orchestrator (a thread pool); a single ``httpx.Client`` is
shared across threads, which httpx supports. An optional fixed per-host interval and an
optional on-disk cache remain available for gentle incremental/seed runs, but both default
off so a full crawl is fast and doesn't duplicate every image on disk.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..config import Settings


@dataclass
class CachedResponse:
    url: str
    status_code: int
    content: bytes
    headers: dict[str, str]
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class PoliteClient:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.cfg = settings.crawl
        self.cache_dir = settings.cache_dir
        if self.cfg.cache_enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_request_at: dict[str, float] = {}
        self._host_delay: dict[str, float] = {}  # host -> robots crawl-delay override
        self._client = httpx.Client(
            follow_redirects=True,
            http2=True,  # multiplex many requests over few connections — big throughput win
            timeout=self.cfg.timeout_seconds,
            limits=httpx.Limits(
                max_connections=self.cfg.concurrency + 8,
                max_keepalive_connections=self.cfg.concurrency + 8,
            ),
            headers={
                "User-Agent": self.cfg.user_agent,
                "From": self.cfg.contact,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    # -- lifecycle -----------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- optional per-host pacing -------------------------------------------

    def set_host_crawl_delay(self, host: str, delay: float | None) -> None:
        if delay:
            with self._lock:
                self._host_delay[host] = float(delay)

    def _throttle(self, host: str) -> None:
        """Enforce an optional fixed gap between requests to a host. No-op by default
        (min_interval_seconds = 0), which is the full-crawl case."""
        interval = max(self.cfg.min_interval_seconds, self._host_delay.get(host, 0.0))
        if interval <= 0:
            return
        with self._lock:
            last = self._last_request_at.get(host)
            now = time.monotonic()
            wait = 0.0 if last is None else interval - (now - last)
            self._last_request_at[host] = now + max(wait, 0.0)
        if wait > 0:
            time.sleep(wait)

    # -- cache (optional) ----------------------------------------------------

    def _cache_path(self, method: str, url: str) -> Path:
        key = hashlib.sha256(f"{method} {url}".encode()).hexdigest()
        return self.cache_dir / key[:2] / f"{key}.json"

    def _read_cache(self, method: str, url: str) -> CachedResponse | None:
        path = self._cache_path(method, url)
        if not path.exists():
            return None
        blob = json.loads(path.read_text(encoding="utf-8"))
        return CachedResponse(
            url=blob["url"],
            status_code=blob["status_code"],
            content=bytes.fromhex(blob["content_hex"]),
            headers=blob["headers"],
            from_cache=True,
        )

    def _write_cache(self, method: str, url: str, resp: CachedResponse) -> None:
        path = self._cache_path(method, url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "url": resp.url,
                    "status_code": resp.status_code,
                    "headers": resp.headers,
                    "content_hex": resp.content.hex(),
                },
            ),
            encoding="utf-8",
        )
        tmp.rename(path)

    # -- request -------------------------------------------------------------

    def get(self, url: str, use_cache: bool | None = None) -> CachedResponse:
        """GET with backoff and optional caching/pacing. Safe to call from many threads."""
        use_cache = self.cfg.cache_enabled if use_cache is None else use_cache
        if use_cache:
            cached = self._read_cache("GET", url)
            if cached is not None:
                return cached

        host = urlsplit(url).netloc
        last_exc: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            self._throttle(host)
            try:
                r = self._client.get(url)
            except httpx.HTTPError as exc:  # transport-level
                last_exc = exc
                self._backoff(attempt)
                continue

            resp = CachedResponse(
                url=str(r.url),
                status_code=r.status_code,
                content=r.content,
                headers={k.lower(): v for k, v in r.headers.items()},
            )
            if resp.status_code in _RETRYABLE_STATUS and attempt < self.cfg.max_retries:
                self._backoff(attempt, retry_after=resp.headers.get("retry-after"))
                continue

            if use_cache:
                self._write_cache("GET", url, resp)
            return resp

        raise httpx.HTTPError(f"GET {url} failed after retries: {last_exc}")

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                time.sleep(min(float(retry_after), self.cfg.backoff_max_seconds))
                return
            except ValueError:
                pass
        delay = min(
            self.cfg.backoff_base_seconds * (2**attempt),
            self.cfg.backoff_max_seconds,
        )
        time.sleep(delay + random.uniform(0, self.cfg.jitter_seconds))
