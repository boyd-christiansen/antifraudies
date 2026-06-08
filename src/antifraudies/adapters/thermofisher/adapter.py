"""The Thermo Fisher adapter: enumerate -> fetch -> parse, emitting the normalized schema."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

from ...crawl.http import PoliteClient
from ...crawl.robots import RobotsPolicy
from ...models import PageSnapshot, ProductRef, ScrapeResult
from ...store.blobs import sha256_hex
from ..base import VendorAdapter
from . import enumerate as tf_enumerate
from .parse import parse_product_page

PRODUCT_URL_TEMPLATE = "https://www.thermofisher.com/antibody/product/{catalog}"


class ThermoFisherAdapter(VendorAdapter):
    vendor = "thermofisher"

    def __init__(self, client: PoliteClient, robots: RobotsPolicy | None = None) -> None:
        self.client = client
        self.robots = robots

    # -- enumeration ---------------------------------------------------------

    def enumerate(self, limit: int | None = None) -> Iterator[ProductRef]:
        yield from tf_enumerate.iter_product_urls(self.client, self.robots, limit=limit)

    def seed(self, entries: Iterable[str]) -> Iterator[ProductRef]:
        """Each entry is a full product URL or a bare catalog number.

        A bare catalog number is resolved through Thermo's catalog-number URL, which
        redirects to the canonical slug URL; we record the canonical URL after fetch.
        """
        for raw in entries:
            entry = raw.strip()
            if not entry or entry.startswith("#"):
                continue
            if entry.startswith("http"):
                catalog = tf_enumerate.catalog_from_url(entry) or entry.rsplit("/", 1)[-1]
                url = entry
            else:
                catalog = entry
                url = PRODUCT_URL_TEMPLATE.format(catalog=catalog)
            yield ProductRef(vendor=self.vendor, catalog_number=catalog, product_url=url)

    # -- fetch ---------------------------------------------------------------

    def fetch_product(self, ref: ProductRef) -> ScrapeResult:
        if self.robots is not None and not self.robots.allowed(ref.product_url):
            raise PermissionError(f"robots.txt disallows {ref.product_url}")

        resp = self.client.get(ref.product_url)
        fetched_at = datetime.now(UTC)
        html = resp.text

        # Snapshot the page as perishable evidence (content-addressed).
        page_sha = sha256_hex(resp.content)
        snapshot = PageSnapshot(
            vendor=self.vendor,
            url=resp.url or ref.product_url,
            catalog_number=ref.catalog_number,
            content_sha256=page_sha,
            byte_size=len(resp.content),
            http_status=resp.status_code,
            fetched_at=fetched_at,
        )

        product, images = parse_product_page(
            html, catalog_number=ref.catalog_number, product_url=snapshot.url
        )
        product.first_seen = fetched_at
        product.last_seen = fetched_at
        for img in images:
            img.http_status = resp.status_code
            img.source_page_sha256 = page_sha

        return ScrapeResult(
            product=product, images=images, page_snapshot=snapshot, raw_html=html
        )
