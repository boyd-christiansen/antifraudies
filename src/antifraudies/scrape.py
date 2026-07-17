"""Scrape orchestration: enumerate -> fetch (concurrently) -> normalize -> persist.

For each product we fetch the page, parse out the product metadata and per-image records,
and download each image's bytes into the content-addressed blob store (deduped across the
whole catalog). We keep the metadata rows and the image pixels; we do NOT store the page
HTML or per-image sidecars — the project cares about which images are reused/altered and
where, not about archiving pages.

Throughput: product pages are fetched by a thread pool (``crawl.concurrency``), with each
worker downloading its product's images. Blob writes happen in the worker threads (atomic,
content-addressed, concurrency-safe); all database writes happen on the main thread (one
connection, single writer). This finishes the full catalog in well under a day.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime

from tqdm import tqdm

from .adapters.base import ProductRef, VendorAdapter
from .config import Settings
from .crawl.http import PoliteClient
from .models import ScrapeResult, VerificationImage
from .store.blobs import BlobStore
from .store.db import Database

log = logging.getLogger(__name__)

_COMMIT_EVERY = 100  # products per database commit (see run())


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
        self.concurrency = max(1, settings.crawl.concurrency)
        self._shutdown = threading.Event()

    def run(
        self,
        refs: Iterable[ProductRef],
        *,
        download_images: bool = True,
        total: int | None = None,
        dry_run: bool = False,
    ) -> ScrapeSummary:
        summary = ScrapeSummary()
        refs_iter = iter(refs)

        if dry_run:
            log.info("dry-run mode: enumerating products without fetching or storing")
            for ref in refs_iter:
                log.debug("would scrape: %s %s", ref.catalog_number, ref.product_url)
                summary.products += 1
            return summary

        # Graceful shutdown: Ctrl-C sets the event so we stop submitting new work.
        prev_handler = signal.getsignal(signal.SIGINT)

        def _on_sigint(sig, frame):
            log.warning("SIGINT received — draining in-flight work and committing…")
            self._shutdown.set()

        signal.signal(signal.SIGINT, _on_sigint)

        pbar = tqdm(
            total=total,
            desc="scraping",
            unit=" products",
            dynamic_ncols=True,
        )

        try:
            with ThreadPoolExecutor(max_workers=self.concurrency) as ex:
                pending: dict[Future, ProductRef] = {}

                def submit_next() -> bool:
                    if self._shutdown.is_set():
                        return False
                    ref = next(refs_iter, None)
                    if ref is None:
                        return False
                    pending[ex.submit(self._fetch_one, ref, download_images)] = ref
                    return True

                # Keep ~2x concurrency in flight so workers never starve between completions.
                for _ in range(self.concurrency * 2):
                    if not submit_next():
                        break

                while pending:
                    done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
                    for fut in done:
                        ref = pending.pop(fut)
                        try:
                            result = fut.result()
                        except Exception as exc:  # noqa: BLE001 — one bad product never aborts the run
                            log.error("product %s failed: %s", ref.catalog_number, exc)
                            summary.errors.append(f"{ref.catalog_number}: {exc}")
                        else:
                            self._write_result(result, summary)
                        submit_next()
                        n = summary.products
                        # Batch database commits: committing per row fsyncs constantly and stalls
                        # the main thread, starving the worker pool.
                        if n and n % _COMMIT_EVERY == 0:
                            self.db.commit()
                        pbar.update(1)
                        pbar.set_postfix(
                            imgs=summary.images,
                            captured=summary.image_bytes_captured,
                            errors=len(summary.errors),
                        )
        finally:
            pbar.close()
            signal.signal(signal.SIGINT, prev_handler)

        self.db.commit()
        log.info(
            "scrape complete: %d products, %d images, %d bytes captured, %d errors",
            summary.products,
            summary.images,
            summary.image_bytes_captured,
            len(summary.errors),
        )
        return summary

    # -- worker (runs in a thread; no DB access) -----------------------------

    def _fetch_one(self, ref: ProductRef, download_images: bool) -> ScrapeResult:
        result = self.adapter.fetch_product(ref)
        if download_images:
            for img in result.images:
                if img.image_url_full:
                    try:
                        self._capture_image_bytes(img)
                    except Exception as exc:  # noqa: BLE001 — a missing image never drops the row
                        log.warning(
                            "image download failed for %s (%s): %s",
                            img.image_filename,
                            img.image_url_full,
                            exc,
                        )
        return result

    def _capture_image_bytes(self, img: VerificationImage) -> None:
        # Don't cache image responses — the blob store already holds the bytes, deduped.
        resp = self.client.get(img.image_url_full, use_cache=False)
        if not resp.ok:
            img.http_status = resp.status_code
            return
        ext = _ext_for(img.image_filename, resp.headers.get("content-type"))
        img.content_sha256 = self.image_blobs.put(resp.content, ext=ext)
        img.byte_size = len(resp.content)
        img.content_type = resp.headers.get("content-type")
        img.http_status = resp.status_code
        img.captured_at = datetime.now(UTC)

    # -- main-thread persistence (single database writer) --------------------

    def _write_result(self, result: ScrapeResult, summary: ScrapeSummary) -> None:
        self.db.upsert_product(result.product)
        for img in result.images:
            self.db.upsert_image(img)
            summary.images += 1
            if img.content_sha256:
                summary.image_bytes_captured += 1
            key = img.provenance.value
            summary.provenance_counts[key] = summary.provenance_counts.get(key, 0) + 1
        summary.products += 1


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
