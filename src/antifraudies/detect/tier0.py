"""Tier 0 detectors — free, run on the whole corpus, pure SQL over the store.

These reproduce the cheapest headline signals from the reporting without touching pixels:

  - metadata_reuse:      one filename timestamp shared across unrelated products (a
                         bookkeeping tell). Internal-only — that's the forensic target.
  - whole_image_reuse:   the *same image bytes* served for two or more different products
                         (exact reuse via the content hash). The most blatant reuse signal.

Both write `findings` rows, labelled by provenance mix, and are idempotent.
"""

from __future__ import annotations

from ..store.db import Database
from .findings import FindingGroup, provenance_pair, severity_for, utcnow, write_findings

VERSION = "0.1"
_PROV_CASE = "CASE WHEN provenance LIKE 'internal%%' THEN 'internal' ELSE 'third_party' END"


def detect_metadata_reuse(db: Database, *, min_products: int = 2) -> int:
    """Internal images whose filename timestamp is shared across >= min_products products."""
    started = utcnow()
    rows = db.conn.execute(
        f"""
        SELECT fn_timestamp AS key,
               array_agg(id ORDER BY id)                       AS image_ids,
               array_agg(DISTINCT catalog_number)              AS catalogs,
               COUNT(DISTINCT catalog_number)                  AS n_products,
               COUNT(*)                                        AS n_images,
               array_agg(DISTINCT {_PROV_CASE})                AS provs
        FROM verification_images
        WHERE fn_timestamp IS NOT NULL AND fn_timestamp <> ''
          AND provenance LIKE 'internal%%'
        GROUP BY fn_timestamp
        HAVING COUNT(DISTINCT catalog_number) >= %s
        ORDER BY n_products DESC
        """,
        (min_products,),
    ).fetchall()

    groups = [
        FindingGroup(
            finding_type="metadata_reuse",
            finding_key=f"ts:{r['key']}",
            member_image_ids=list(r["image_ids"]),
            member_catalogs=list(r["catalogs"]),
            n_products=r["n_products"],
            provenance_pair=provenance_pair(r["provs"]),
            score=float(r["n_products"]),
            severity=severity_for(r["n_products"]),
            detail={
                "timestamp": r["key"], "n_images": r["n_images"],
                "signal": "shared_filename_timestamp",
            },
        )
        for r in rows
    ]
    return write_findings(
        db, detector="tier0.metadata_reuse", version=VERSION,
        params={"min_products": min_products, "scope": "internal", "signal": "fn_timestamp"},
        groups=groups, corpus_count=_corpus_count(db), started_at=started,
    )


def detect_whole_image_reuse(db: Database, *, min_products: int = 2) -> int:
    """Identical image bytes (content hash) served for >= min_products different products."""
    started = utcnow()
    rows = db.conn.execute(
        f"""
        SELECT content_sha256 AS key,
               array_agg(id ORDER BY id)                       AS image_ids,
               array_agg(DISTINCT catalog_number)              AS catalogs,
               COUNT(DISTINCT catalog_number)                  AS n_products,
               COUNT(*)                                        AS n_images,
               array_agg(DISTINCT {_PROV_CASE})                AS provs,
               array_agg(DISTINCT image_filename)              AS filenames
        FROM verification_images
        WHERE content_sha256 IS NOT NULL
        GROUP BY content_sha256
        HAVING COUNT(DISTINCT catalog_number) >= %s
        ORDER BY n_products DESC
        """,
        (min_products,),
    ).fetchall()

    groups = [
        FindingGroup(
            finding_type="whole_image_reuse",
            finding_key=f"sha:{r['key']}",
            member_image_ids=list(r["image_ids"]),
            member_catalogs=list(r["catalogs"]),
            n_products=r["n_products"],
            provenance_pair=provenance_pair(r["provs"]),
            # exact byte reuse across products is categorically strong: floor at medium
            score=float(r["n_products"]),
            severity=_at_least_medium(severity_for(r["n_products"])),
            detail={
                "content_sha256": r["key"], "n_images": r["n_images"],
                "filenames": list(r["filenames"]), "signal": "identical_bytes_across_products",
            },
        )
        for r in rows
    ]
    return write_findings(
        db, detector="tier0.whole_image_reuse", version=VERSION,
        params={"min_products": min_products, "signal": "content_sha256"},
        groups=groups, corpus_count=_corpus_count(db), started_at=started,
    )


def run_all(db: Database) -> dict[str, int]:
    return {
        "metadata_reuse": detect_metadata_reuse(db),
        "whole_image_reuse": detect_whole_image_reuse(db),
    }


def _corpus_count(db: Database) -> int:
    return db.conn.execute("SELECT COUNT(*) AS n FROM verification_images").fetchone()["n"]


def _at_least_medium(sev: str) -> str:
    return "medium" if sev == "low" else sev
