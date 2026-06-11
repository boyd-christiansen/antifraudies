"""Shared finding model + idempotent writer for all detectors.

A *finding* groups the images implicated by one signal (a shared timestamp, a reused image,
a near-duplicate cluster, ...). Its identity is `(finding_type, finding_key)` so detectors
can be re-run without duplicating rows. Every write also logs a `detector_runs` row for
reproducibility (detector, version, params, corpus size, count).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from psycopg.types.json import Jsonb

from ..store.db import Database


@dataclass
class FindingGroup:
    finding_type: str
    finding_key: str  # deterministic identity within finding_type
    member_image_ids: list[int]
    member_catalogs: list[str]
    n_products: int
    provenance_pair: str | None
    score: float
    severity: str
    detail: dict = field(default_factory=dict)


def params_hash(params: dict) -> str:
    blob = json.dumps(params, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def severity_for(n_products: int) -> str:
    if n_products >= 10:
        return "high"
    if n_products >= 4:
        return "medium"
    return "low"


def provenance_pair(provenances: list[str]) -> str:
    """Canonical label for a finding's provenance mix (e.g. internal-third_party).

    Takes the raw provenance values of the members and collapses to internal/third_party.
    A match that mixes internal and third-party is a *different, stronger* signal than an
    internal-only one, so we always record it.
    """
    cats = set()
    for p in provenances:
        cats.add("internal" if p.startswith("internal") else "third_party")
    return "-".join(sorted(cats))


def write_findings(
    db: Database,
    *,
    detector: str,
    version: str,
    params: dict,
    groups: list[FindingGroup],
    corpus_count: int,
    started_at: datetime,
) -> int:
    """Upsert a detector's findings and log the run. Returns the number written."""
    ph = params_hash(params)
    for g in groups:
        db.conn.execute(
            """
            INSERT INTO findings
                (finding_type, finding_key, score, severity, n_products,
                 member_image_ids, member_catalogs, provenance_pair, detail,
                 detector, detector_version, params_hash)
            VALUES
                (%(finding_type)s, %(finding_key)s, %(score)s, %(severity)s, %(n_products)s,
                 %(member_image_ids)s, %(member_catalogs)s, %(provenance_pair)s, %(detail)s,
                 %(detector)s, %(detector_version)s, %(params_hash)s)
            ON CONFLICT (finding_type, finding_key) DO UPDATE SET
                score            = EXCLUDED.score,
                severity         = EXCLUDED.severity,
                n_products       = EXCLUDED.n_products,
                member_image_ids = EXCLUDED.member_image_ids,
                member_catalogs  = EXCLUDED.member_catalogs,
                provenance_pair  = EXCLUDED.provenance_pair,
                detail           = EXCLUDED.detail,
                detector         = EXCLUDED.detector,
                detector_version = EXCLUDED.detector_version,
                params_hash      = EXCLUDED.params_hash,
                created_at       = now()
            """,
            {
                "finding_type": g.finding_type,
                "finding_key": g.finding_key,
                "score": g.score,
                "severity": g.severity,
                "n_products": g.n_products,
                "member_image_ids": g.member_image_ids,
                "member_catalogs": g.member_catalogs,
                "provenance_pair": g.provenance_pair,
                "detail": Jsonb(g.detail),
                "detector": detector,
                "detector_version": version,
                "params_hash": ph,
            },
        )
    db.conn.execute(
        """
        INSERT INTO detector_runs
            (detector, version, params, corpus_count, findings_written, started_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (detector, version, Jsonb(params), corpus_count, len(groups), started_at),
    )
    db.commit()
    return len(groups)


def utcnow() -> datetime:
    return datetime.now(UTC)
