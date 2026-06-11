"""SQLite access layer for the normalized evidence store.

Holds the queryable records and a few cross-image query helpers that demonstrate the
whole-corpus comparisons phase 2 will build on (e.g. "which images share a content
hash" or "which unrelated products share an image filename timestamp"). Upserts are
idempotent so re-scraping a product never duplicates rows.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..models import Product, VerificationImage

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
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
            VALUES (:vendor, :catalog_number, :product_url, :product_name, :target, :clone,
                    :rrid, :first_seen, :last_seen)
            ON CONFLICT(vendor, catalog_number) DO UPDATE SET
                product_url  = excluded.product_url,
                product_name = COALESCE(excluded.product_name, products.product_name),
                target       = COALESCE(excluded.target, products.target),
                clone        = COALESCE(excluded.clone, products.clone),
                rrid         = COALESCE(excluded.rrid, products.rrid),
                -- keep the EARLIEST first_seen, advance last_seen
                first_seen   = MIN(COALESCE(products.first_seen, excluded.first_seen),
                                   COALESCE(excluded.first_seen, products.first_seen)),
                last_seen    = MAX(COALESCE(products.last_seen, excluded.last_seen),
                                   COALESCE(excluded.last_seen, products.last_seen))
            """,
            {
                "vendor": p.vendor,
                "catalog_number": p.catalog_number,
                "product_url": p.product_url,
                "product_name": p.product_name,
                "target": p.target,
                "clone": p.clone,
                "rrid": p.rrid,
                "first_seen": _iso(p.first_seen),
                "last_seen": _iso(p.last_seen),
            },
        )

    def upsert_image(self, img: VerificationImage) -> None:
        fn = img.filename_metadata
        self.conn.execute(
            """
            INSERT INTO verification_images
                (vendor, catalog_number, vendor_image_id, provenance,
                 provenance_disagreement, source_type_raw, application_abbrev,
                 application_name, caption, short_caption, title, alt_tag, journal_text,
                 benchsci_pubmed_id, image_filename, image_url_full, image_url_variants,
                 fn_catalog, fn_target, fn_application, fn_av_marker, fn_timestamp,
                 fn_pubmed_id, content_sha256, byte_size, content_type, http_status,
                 captured_at)
            VALUES
                (:vendor, :catalog_number, :vendor_image_id, :provenance,
                 :provenance_disagreement, :source_type_raw, :application_abbrev,
                 :application_name, :caption, :short_caption, :title, :alt_tag,
                 :journal_text, :benchsci_pubmed_id, :image_filename, :image_url_full,
                 :image_url_variants, :fn_catalog, :fn_target, :fn_application,
                 :fn_av_marker, :fn_timestamp, :fn_pubmed_id, :content_sha256, :byte_size,
                 :content_type, :http_status, :captured_at)
            ON CONFLICT(vendor, catalog_number, image_filename) DO UPDATE SET
                vendor_image_id         = excluded.vendor_image_id,
                provenance              = excluded.provenance,
                provenance_disagreement = excluded.provenance_disagreement,
                source_type_raw         = excluded.source_type_raw,
                caption                 = excluded.caption,
                content_sha256          = COALESCE(excluded.content_sha256,
                                                   verification_images.content_sha256),
                byte_size               = COALESCE(excluded.byte_size,
                                                   verification_images.byte_size),
                content_type            = COALESCE(excluded.content_type,
                                                   verification_images.content_type),
                http_status             = excluded.http_status,
                captured_at             = COALESCE(excluded.captured_at,
                                                   verification_images.captured_at)
            """,
            {
                "vendor": img.vendor,
                "catalog_number": img.catalog_number,
                "vendor_image_id": img.vendor_image_id,
                "provenance": img.provenance.value,
                "provenance_disagreement": img.provenance_disagreement,
                "source_type_raw": img.source_type_raw,
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
                "image_url_variants": json.dumps(img.image_url_variants),
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
                "captured_at": _iso(img.captured_at),
            },
        )

    # ------------------------------------------------------------------ reads

    def count_images(self, provenance: str | None = None) -> int:
        if provenance:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM verification_images WHERE provenance = ?",
                (provenance,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM verification_images").fetchone()
        return row["n"]

    def images_sharing_content(self) -> list[sqlite3.Row]:
        """Cross-image: content hashes that appear on more than one product (whole-image
        reuse). A phase-2 building block, demonstrated here on phase-1 data."""
        return self.conn.execute(
            """
            SELECT content_sha256,
                   COUNT(DISTINCT catalog_number) AS n_products,
                   GROUP_CONCAT(DISTINCT catalog_number) AS products
            FROM verification_images
            WHERE content_sha256 IS NOT NULL
            GROUP BY content_sha256
            HAVING n_products > 1
            ORDER BY n_products DESC
            """
        ).fetchall()

    def images_sharing_timestamp(self, internal_only: bool = True) -> list[sqlite3.Row]:
        """Cross-image: filename timestamps shared across unrelated products."""
        where = "fn_timestamp IS NOT NULL AND fn_timestamp != ''"
        if internal_only:
            where += " AND provenance LIKE 'internal_%'"
        return self.conn.execute(
            f"""
            SELECT fn_timestamp,
                   COUNT(DISTINCT catalog_number) AS n_products,
                   COUNT(*) AS n_images
            FROM verification_images
            WHERE {where}
            GROUP BY fn_timestamp
            HAVING n_products > 1
            ORDER BY n_products DESC
            """
        ).fetchall()


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None
