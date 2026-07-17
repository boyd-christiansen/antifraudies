"""Tests for antifraudies.crawl.http.PoliteClient and CachedResponse."""

from __future__ import annotations

import time

import httpx

from antifraudies.config import load_settings
from antifraudies.crawl.http import CachedResponse, PoliteClient


def _make_settings(tmp_path, *, cache_enabled=False, max_retries=2):
    """Build a real Settings object with short backoff and optional caching."""
    settings = load_settings()
    settings.crawl.max_retries = max_retries
    settings.crawl.backoff_base_seconds = 0.01
    settings.crawl.backoff_max_seconds = 0.05
    settings.crawl.jitter_seconds = 0.0
    settings.crawl.cache_enabled = cache_enabled
    settings.crawl.min_interval_seconds = 0.0
    # Point data/cache dirs into tmp_path so tests are isolated.
    settings.paths.data_dir = str(tmp_path / "data")
    settings.paths.cache_subdir = "cache"
    return settings


def _swap_transport(client: PoliteClient, handler) -> None:
    """Replace the underlying httpx client with a mock transport."""
    client._client = httpx.Client(transport=httpx.MockTransport(handler))


# ── GET basics ──────────────────────────────────────────────────────────────


def test_successful_get(tmp_path, monkeypatch):
    """A 200 response populates CachedResponse fields correctly."""
    monkeypatch.setattr(time, "sleep", lambda _: None)
    settings = _make_settings(tmp_path)

    with PoliteClient(settings) as client:
        _swap_transport(client, lambda req: httpx.Response(200, content=b"ok"))
        resp = client.get("http://example.com/page")

    assert resp.status_code == 200
    assert resp.content == b"ok"
    assert resp.from_cache is False


def test_retry_on_503(tmp_path, monkeypatch):
    """Client retries on 503 and succeeds when the next attempt returns 200."""
    monkeypatch.setattr(time, "sleep", lambda _: None)
    settings = _make_settings(tmp_path)
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"recovered")

    with PoliteClient(settings) as client:
        _swap_transport(client, handler)
        resp = client.get("http://example.com/flaky")

    assert resp.status_code == 200
    assert resp.content == b"recovered"
    assert call_count == 2


def test_retry_on_429_with_retry_after(tmp_path, monkeypatch):
    """429 with a Retry-After header is honoured (sleep is monkeypatched)."""
    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))
    settings = _make_settings(tmp_path)
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, content=b"ok")

    with PoliteClient(settings) as client:
        _swap_transport(client, handler)
        resp = client.get("http://example.com/ratelimit")

    assert resp.status_code == 200
    # The sleep for the Retry-After header should have been called.
    assert any(s > 0 for s in sleep_calls)


def test_max_retries_exceeded(tmp_path, monkeypatch):
    """Raises httpx.HTTPError when all retry attempts are exhausted."""
    monkeypatch.setattr(time, "sleep", lambda _: None)
    settings = _make_settings(tmp_path, max_retries=2)

    def handler(request):
        return httpx.Response(503)

    with PoliteClient(settings) as client:
        _swap_transport(client, handler)
        try:
            client.get("http://example.com/down")
            raised = False
        except httpx.HTTPError:
            raised = True

    assert raised, "Expected httpx.HTTPError after exhausting retries"


# ── Caching ─────────────────────────────────────────────────────────────────


def test_cache_hit(tmp_path, monkeypatch):
    """Second GET for the same URL returns from_cache=True."""
    monkeypatch.setattr(time, "sleep", lambda _: None)
    settings = _make_settings(tmp_path, cache_enabled=True)
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=b"cached-body")

    with PoliteClient(settings) as client:
        _swap_transport(client, handler)
        resp1 = client.get("http://example.com/cacheable")
        resp2 = client.get("http://example.com/cacheable")

    assert resp1.from_cache is False
    assert resp2.from_cache is True
    assert resp2.content == b"cached-body"
    assert call_count == 1  # transport called only once


def test_cache_miss(tmp_path, monkeypatch):
    """First request is always a cache miss."""
    monkeypatch.setattr(time, "sleep", lambda _: None)
    settings = _make_settings(tmp_path, cache_enabled=True)

    with PoliteClient(settings) as client:
        _swap_transport(client, lambda req: httpx.Response(200, content=b"fresh"))
        resp = client.get("http://example.com/never-seen")

    assert resp.from_cache is False


# ── CachedResponse properties ──────────────────────────────────────────────


def test_cached_response_ok_property():
    """.ok is True for 2xx, False otherwise."""
    assert CachedResponse(url="u", status_code=200, content=b"", headers={}).ok is True
    assert CachedResponse(url="u", status_code=201, content=b"", headers={}).ok is True
    assert CachedResponse(url="u", status_code=404, content=b"", headers={}).ok is False
    assert CachedResponse(url="u", status_code=500, content=b"", headers={}).ok is False


def test_cached_response_text_property():
    """.text decodes content as UTF-8."""
    body = "café ☕"
    resp = CachedResponse(
        url="u",
        status_code=200,
        content=body.encode("utf-8"),
        headers={},
    )
    assert resp.text == body
