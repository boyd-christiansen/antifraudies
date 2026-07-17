"""PostgreSQL access layer for the normalized store (psycopg3 + pgvector).

Holds the queryable records, derived features (incl. embeddings), and findings. A few
cross-image query helpers demonstrate the whole-corpus comparisons phase 2 builds on.
Upserts are idempotent so re-scraping a product never duplicates rows.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..models import Product, VerificationImage

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _split_statements(sql: str) -> list[str]:
    """Split a DDL script into statements. Strip ``--`` comments FIRST (they may contain ';'),
    then split on ';'. Safe here: our DDL has no string literals containing '--' or ';'."""
    stripped = []
    for line in sql.splitlines():
        idx = line.find("--")
        stripped.append(line if idx < 0 else line[:idx])
    return [s.strip() for s in "\n".join(stripped).split(";") if s.strip()]


class Database:
    def __init__(self, dsn: str, *, max_retries: int = 3, retry_delay: float = 2.0) -> None:
        self.dsn = dsn
        self.conn = self._connect_with_retry(dsn, max_retries, retry_delay)
        register_vector(self.conn)
        self._init_schema()

    @staticmethod
    def _connect_with_retry(
        dsn: str, max_retries: int, retry_delay: float
    ) -> psycopg.Connection:
        """Connect to PostgreSQL with exponential backoff on transient failures."""
        import logging
        import time

        log = logging.getLogger(__name__)
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
            except psycopg.OperationalError as exc:
                last_exc = exc
                if attempt < max_retries:
                    delay = retry_delay * (2 ** attempt)
                    log.warning(
                        "Postgres connection attempt %d/%d failed: %s — retrying in %.1fs",
                        attempt + 1,
                        max_retries + 1,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
        raise psycopg.OperationalError(
            f"failed to connect after {max_retries + 1} attempts: {last_exc}"
        ) from last_exc

    def _init_schema(self) -> None:
        with self.conn.cursor() as cur:
            for stmt in _split_statements(SCHEMA_PATH.read_text(encoding="utf-8")):
                cur.execute(stmt)
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ writes

    def upsert_product(self, p: Product) -> None:
        self.conn.execute(
            """
            INSERT INTO products
                (vendor, catalog_number, product_url, product_name, target, clone, rrid,
                 first_seen, last_seen)
            VALUES (%(vendor)s, %(catalog_number)s, %(product_url)s, %(product_name)s,
                    %(target)s, %(clone)s, %(rrid)s, %(first_seen)s, %(last_seen)s)
            ON CONFLICT (vendor, catalog_number) DO UPDATE SET
                product_url  = EXCLUDED.product_url,
                product_name = COALESCE(EXCLUDED.product_name, products.product_name),
                target       = COALESCE(EXCLUDED.target, products.target),
                clone        = COALESCE(EXCLUDED.clone, products.clone),
                rrid         = COALESCE(EXCLUDED.rrid, products.rrid),
                first_seen   = LEAST(COALESCE(products.first_seen, EXCLUDED.first_seen),
                                     COALESCE(EXCLUDED.first_seen, products.first_seen)),
                last_seen    = GREATEST(COALESCE(products.last_seen, EXCLUDED.last_seen),
                                        COALESCE(EXCLUDED.last_seen, products.last_seen))
            """,
            {
                "vendor": p.vendor,
                "catalog_number": p.catalog_number,
                "product_url": p.product_url,
                "product_name": p.product_name,
                "target": p.target,
                "clone": p.clone,
                "rrid": p.rrid,
                "first_seen": p.first_seen,
                "last_seen": p.last_seen,
            },
        )

    def upsert_image(self, img: VerificationImage) -> None:
        fn = img.filename_metadata
        self.conn.execute(
            """
            INSERT INTO verification_images
                (vendor, catalog_number, vendor_image_id, provenance,
                 provenance_disagreement, source_type_raw, modality, modality_confidence,
                 application_abbrev, application_name, caption, short_caption, title,
                 alt_tag, journal_text, benchsci_pubmed_id, image_filename, image_url_full,
                 image_url_variants, fn_catalog, fn_target, fn_application, fn_av_marker,
                 fn_timestamp, fn_pubmed_id, content_sha256, byte_size, content_type,
                 http_status, captured_at)
            VALUES
                (%(vendor)s, %(catalog_number)s, %(vendor_image_id)s, %(provenance)s,
                 %(provenance_disagreement)s, %(source_type_raw)s, %(modality)s,
                 %(modality_confidence)s, %(application_abbrev)s, %(application_name)s,
                 %(caption)s, %(short_caption)s, %(title)s, %(alt_tag)s, %(journal_text)s,
                 %(benchsci_pubmed_id)s, %(image_filename)s, %(image_url_full)s,
                 %(image_url_variants)s, %(fn_catalog)s, %(fn_target)s, %(fn_application)s,
                 %(fn_av_marker)s, %(fn_timestamp)s, %(fn_pubmed_id)s, %(content_sha256)s,
                 %(byte_size)s, %(content_type)s, %(http_status)s, %(captured_at)s)
            ON CONFLICT (vendor, catalog_number, image_filename) DO UPDATE SET
                vendor_image_id         = EXCLUDED.vendor_image_id,
                provenance              = EXCLUDED.provenance,
                provenance_disagreement = EXCLUDED.provenance_disagreement,
                source_type_raw         = EXCLUDED.source_type_raw,
                modality                = EXCLUDED.modality,
                modality_confidence     = EXCLUDED.modality_confidence,
                caption                 = EXCLUDED.caption,
                content_sha256          = COALESCE(EXCLUDED.content_sha256,
                                                   verification_images.content_sha256),
                byte_size               = COALESCE(EXCLUDED.byte_size,
                                                   verification_images.byte_size),
                content_type            = COALESCE(EXCLUDED.content_type,
                                                   verification_images.content_type),
                http_status             = EXCLUDED.http_status,
                captured_at             = COALESCE(EXCLUDED.captured_at,
                                                   verification_images.captured_at)
            """,
            {
                "vendor": img.vendor,
                "catalog_number": img.catalog_number,
                "vendor_image_id": img.vendor_image_id,
                "provenance": img.provenance.value,
                "provenance_disagreement": img.provenance_disagreement,
                "source_type_raw": img.source_type_raw,
                "modality": img.modality.value,
                "modality_confidence": img.modality_confidence,
                "application_abbrev": img.application_abbrev,
                "application_name": img.application_name,
                "caption": img.caption,
                "short_caption": img.short_caption,
                "title": img.title,
                "alt_tag": img.alt_tag,
                "journal_text": img.journal_text,
                "benchsci_pubmed_id": img.benchsci_pubmed_id,
                "image_filename": img.image_filename,
                "image_url_full": img.image_url_full,
                "image_url_variants": Jsonb(img.image_url_variants),
                "fn_catalog": fn.catalog_token if fn else None,
                "fn_target": fn.target_token if fn else None,
                "fn_application": fn.application_token if fn else None,
                "fn_av_marker": int(fn.advanced_verification_marker) if fn else None,
                "fn_timestamp": fn.timestamp_token if fn else None,
                "fn_pubmed_id": fn.pubmed_id if fn else None,
                "content_sha256": img.content_sha256,
                "byte_size": img.byte_size,
                "content_type": img.content_type,
                "http_status": img.http_status,
                "captured_at": img.captured_at,
            },
        )

    # ------------------------------------------------------------------ reads

    def scraped_catalogs(self, vendor: str) -> set[str]:
        """Catalog numbers already scraped for a vendor — used by `scrape --resume` to skip
        them, so a long crawl can be re-run without restarting from the top."""
        rows = self.conn.execute(
            "SELECT catalog_number FROM products WHERE vendor = %s", (vendor,)
        ).fetchall()
        return {r["catalog_number"] for r in rows}

    def count_images(self, provenance: str | None = None) -> int:
        if provenance:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM verification_images WHERE provenance = %s",
                (provenance,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM verification_images").fetchone()
        return row["n"]

    def modality_matrix(self) -> list[dict]:
        """Counts by provenance x rendered modality — sizes each forensic stream."""
        return self.conn.execute(
            """
            SELECT provenance, modality, COUNT(*) AS n
            FROM verification_images
            GROUP BY provenance, modality
            ORDER BY provenance, n DESC
            """
        ).fetchall()

    def images_sharing_content(self) -> list[dict]:
        """Cross-image: content hashes that appear on more than one product (whole-image
        reuse)."""
        return self.conn.execute(
            """
            SELECT content_sha256,
                   COUNT(DISTINCT catalog_number) AS n_products,
                   string_agg(DISTINCT catalog_number, ',') AS products
            FROM verification_images
            WHERE content_sha256 IS NOT NULL
            GROUP BY content_sha256
            HAVING COUNT(DISTINCT catalog_number) > 1
            ORDER BY n_products DESC
            """
        ).fetchall()

    def images_sharing_timestamp(self, internal_only: bool = True) -> list[dict]:
        """Cross-image: filename timestamps shared across unrelated products."""
        where = "fn_timestamp IS NOT NULL AND fn_timestamp <> ''"
        params: list[str] = []
        if internal_only:
            where += " AND provenance LIKE %s"
            params.append("internal%")  # LIKE wildcard inside a parameter value
        return self.conn.execute(
            f"""
            SELECT fn_timestamp,
                   COUNT(DISTINCT catalog_number) AS n_products,
                   COUNT(*) AS n_images
            FROM verification_images
            WHERE {where}
            GROUP BY fn_timestamp
            HAVING COUNT(DISTINCT catalog_number) > 1
            ORDER BY n_products DESC
            """,
            params,
        ).fetchall()
