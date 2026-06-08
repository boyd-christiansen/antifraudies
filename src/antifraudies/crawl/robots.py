"""robots.txt fetching and enforcement.

We fetch robots.txt through the polite client (so it carries our honest UA and the
realistic Accept headers the target's edge requires), parse it with the stdlib parser,
and expose ``allowed`` / ``crawl_delay``. The Thermo Fisher adapter uses this to refuse
disallowed paths (e.g. the search API) and to enumerate only via the allowed sitemaps.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .http import PoliteClient


class RobotsPolicy:
    def __init__(self, client: PoliteClient, user_agent: str) -> None:
        self.client = client
        self.user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}

    def _parser_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._parsers:
            rp = RobotFileParser()
            robots_url = f"{parts.scheme}://{host}/robots.txt"
            try:
                resp = self.client.get(robots_url)
                if resp.ok:
                    rp.parse(resp.text.splitlines())
                else:
                    # No usable robots.txt -> default to permissive but record nothing.
                    rp.parse([])
            except Exception:
                rp.parse([])
            # Apply any robots crawl-delay to the client's per-host pacing.
            delay = rp.crawl_delay(self.user_agent)
            if delay:
                self.client.set_host_crawl_delay(host, float(delay))
            self._parsers[host] = rp
        return self._parsers[host]

    def allowed(self, url: str) -> bool:
        return self._parser_for(url).can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        delay = self._parser_for(url).crawl_delay(self.user_agent)
        return float(delay) if delay else None
