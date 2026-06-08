"""Optional external evidence preservation via the Wayback Machine.

Evidence is perishable: the vendor is aware of the scrutiny and may quietly swap or
remove images. Beyond storing original bytes locally, we can submit the source page to
the Internet Archive's "Save Page Now" so an independent, timestamped copy exists.

This is OFF by default (it is outward-facing and slow) and best-effort: a failure here
never aborts a scrape, it just leaves ``wayback_url`` unset.
"""

from __future__ import annotations

import httpx

SAVE_ENDPOINT = "https://web.archive.org/save/"


def save_page_now(url: str, *, user_agent: str, timeout: float = 60.0) -> str | None:
    """Submit ``url`` to the Wayback Machine. Returns the archived URL, or None on failure."""
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(SAVE_ENDPOINT + url, headers={"User-Agent": user_agent})
        # The archived snapshot location is returned in a Content-Location or Link header,
        # or we can construct it from the final redirected URL.
        loc = resp.headers.get("content-location")
        if loc:
            return "https://web.archive.org" + loc
        if "/web/" in str(resp.url):
            return str(resp.url)
        return None
    except Exception:
        return None
