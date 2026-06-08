"""Catalog enumeration for Thermo Fisher via the robots-allowed sitemaps.

robots.txt names ``/antibody/sitemap-AntibodiesIndex.xml``, a sitemap index pointing at
~18 child sitemaps (primary antibody product pages 1..5, secondary antibodies, isotype
controls, ...), each listing the actual ``/antibody/product/...`` URLs. We enumerate via
these. We deliberately do NOT use the search API: robots.txt disallows it
(``/search/results*``, ``/antibody/primary/query/``).

The catalog number — the stable primary key — is the last path segment of a product URL.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ...crawl.http import PoliteClient
from ...crawl.robots import RobotsPolicy
from ...models import ProductRef

VENDOR = "thermofisher"
SITEMAP_INDEX = "https://www.thermofisher.com/antibody/sitemap-AntibodiesIndex.xml"

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
# A product URL looks like /antibody/product/<slug>/<CATALOG>
_PRODUCT_URL_RE = re.compile(r"/antibody/product/[^/]+/([A-Za-z0-9.\-]+)/?$")


def _locs(client: PoliteClient, url: str) -> list[str]:
    resp = client.get(url)
    if not resp.ok:
        return []
    return _LOC_RE.findall(resp.text)


def catalog_from_url(url: str) -> str | None:
    m = _PRODUCT_URL_RE.search(url.split("?")[0])
    return m.group(1) if m else None


def iter_product_urls(
    client: PoliteClient,
    robots: RobotsPolicy | None = None,
    *,
    limit: int | None = None,
) -> Iterator[ProductRef]:
    """Walk the sitemap index -> child sitemaps -> product URLs, yielding ProductRefs."""
    yielded = 0
    for child in _locs(client, SITEMAP_INDEX):
        if "ProductPages" not in child:
            continue  # skip non-product sitemaps (e.g. category/landing indexes)
        for product_url in _locs(client, child):
            catalog = catalog_from_url(product_url)
            if not catalog:
                continue
            if robots is not None and not robots.allowed(product_url):
                continue
            yield ProductRef(vendor=VENDOR, catalog_number=catalog, product_url=product_url)
            yielded += 1
            if limit is not None and yielded >= limit:
                return
