"""Scrape orchestration: enumerate -> fetch -> normalize -> persist as preserved evidence.

This ties the polite crawler, the vendor adapter, and the evidence store together. For
each product it: snapshots the page bytes (content-addressed), upserts the product and its
verification images, downloads each image's original bytes (immutable, hashed, with a JSON
sidecar), and optionally submits the page to the Wayback Machine.

Framing discipline: this captures and normalizes evidence. It does not score or judge.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .adapters.base import ProductRef, VendorAdapter
from .config import Settings
from .crawl.archive import save_page_now
from .crawl.http import PoliteClient
from .models import ScrapeResult
from .store.blobs import BlobStore
from .store.db import Database


@dataclass
class ScrapeSummary:
    products: int = 0
    images: int = 0
    image_bytes_captured: int = 0
    provenance_counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class ScrapeOrchestrator:
    def __init__(
        self,
        settings: Settings,
        client: PoliteClient,
        adapter: VendorAdapter,
        db: Database,
    ) -> None:
        self.settings = settings
        self.client = client
        self.adapter = adapter
        self.db = db
        self.image_blobs = BlobStore(settings.blobs_dir)
        self.page_blobs = BlobStore(settings.pages_dir)

    def run(
        self,
        refs: Iterable[ProductRef],
        *,
        download_images: bool = True,
    ) -> ScrapeSummary:
        summary = ScrapeSummary()
        for ref in refs:
            try:
                result = self.adapter.fetch_product(ref)
            except Exception as exc:  # noqa: BLE001 — one bad product must not abort the run
                summary.errors.append(f"{ref.catalog_number}: {exc}")
                continue
            self._persist(result, download_images=download_images, summary=summary)
            summary.products += 1
        return summary

    # ------------------------------------------------------------------ persist

    def _persist(
        self, result: ScrapeResult, *, download_images: bool, summary: ScrapeSummary
    ) -> None:
        # 1. Page snapshot bytes (perishable evidence) -> content-addressed store.
        self.page_blobs.put(result.raw_html.encode("utf-8"), ext="html")

        # 2. Optional external archival of the page.
        if self.settings.archive.wayback_save_pages:
            result.page_snapshot.wayback_url = save_page_now(
                result.page_snapshot.url, user_agent=self.settings.crawl.user_agent
            )

        self.db.upsert_page_snapshot(result.page_snapshot)
        self.db.upsert_product(result.product)

        # 3. Each verification image: download original bytes, hash, sidecar, record.
        for img in result.images:
            if download_images and img.image_url_full:
                try:
                    self._capture_image_bytes(img, summary)
                except Exception as exc:  # noqa: BLE001
                    summary.errors.append(f"{img.image_filename}: {exc}")
            self.db.upsert_image(img)
            summary.images += 1
            key = img.provenance.value
            summary.provenance_counts[key] = summary.provenance_counts.get(key, 0) + 1

    def _capture_image_bytes(self, img, summary: ScrapeSummary) -> None:
        resp = self.client.get(img.image_url_full)
        if not resp.ok:
            img.http_status = resp.status_code
            return
        ext = _ext_for(img.image_filename, resp.headers.get("content-type"))
        digest = self.image_blobs.put(resp.content, ext=ext)
        img.content_sha256 = digest
        img.byte_size = len(resp.content)
        img.content_type = resp.headers.get("content-type")
        img.http_status = resp.status_code
        img.captured_at = datetime.now(UTC)
        # Self-describing sidecar so the raw evidence stands alone on disk.
        self.image_blobs.write_sidecar(digest, img.model_dump(mode="json"))
        summary.image_bytes_captured += 1


def _ext_for(filename: str, content_type: str | None) -> str:
    name = filename.split("?")[0]
    if "." in name:
        return name.rsplit(".", 1)[-1].lower()
    if content_type and "/" in content_type:
        return content_type.split("/", 1)[-1].split(";")[0].strip().lower()
    return "bin"


def iter_seed_file(path) -> Iterator[str]:
    with open(path, encoding="utf-8") as fh:
        yield from fh
