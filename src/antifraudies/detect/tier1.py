"""Tier 1 detectors — cheap, run on all images with captured bytes.

  - features:        compute pHash/dHash/grayscale/contrast once per image (features.py).
  - near_duplicate:  cluster images whose pHash is within a small Hamming distance but are
                     NOT byte-identical (exact reuse is Tier 0's whole_image_reuse), spanning
                     more than one product. This catches "same image, lightly edited/recompressed"
                     and is a stepping stone to the embedding+ANN similarity in phase 2.

The near-dup pass here is O(n^2) over pHashes — fine for a sample. At catalog scale this
becomes an LSH/BK-tree index or the pgvector embedding ANN (designed for, not built here).
"""

from __future__ import annotations

from ..config import get_settings
from ..store.blobs import BlobStore
from ..store.db import Database
from .features import compute_features
from .findings import FindingGroup, provenance_pair, severity_for, utcnow, write_findings

VERSION = "0.1"
DEFAULT_HAMMING = 10  # max pHash Hamming distance to call two images near-duplicate


class _UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def cluster_near_duplicates(items: list[dict], max_hamming: int) -> list[list[dict]]:
    """Pure clustering: union items whose pHash differs by <= max_hamming (but aren't
    byte-identical), then keep only clusters that span >1 product. ``items`` are dicts with
    keys id, catalog, prov, sha, bits (pHash as int). Returns lists of member dicts."""
    uf = _UnionFind([it["id"] for it in items])
    n = len(items)
    for i in range(n):
        a = items[i]
        for j in range(i + 1, n):
            b = items[j]
            if a["sha"] is not None and a["sha"] == b["sha"]:
                continue  # exact reuse → Tier 0, not here
            if (a["bits"] ^ b["bits"]).bit_count() <= max_hamming:
                uf.union(a["id"], b["id"])

    by_root: dict[int, list[dict]] = {}
    for it in items:
        by_root.setdefault(uf.find(it["id"]), []).append(it)

    clusters = []
    for members in by_root.values():
        if len(members) < 2:
            continue
        if len({m["catalog"] for m in members}) < 2:  # cross-product only
            continue
        clusters.append(members)
    return clusters


def detect_near_duplicate(db: Database, *, max_hamming: int = DEFAULT_HAMMING) -> int:
    """Cluster near-identical (but not byte-identical) images that span >1 product."""
    started = utcnow()
    rows = db.conn.execute(
        """
        SELECT vi.id, vi.catalog_number, vi.provenance, vi.content_sha256, f.phash
        FROM image_features f
        JOIN verification_images vi ON vi.id = f.image_id
        WHERE f.phash IS NOT NULL
        """
    ).fetchall()

    items = [
        {"id": r["id"], "catalog": r["catalog_number"], "prov": r["provenance"],
         "sha": r["content_sha256"], "bits": int(r["phash"], 16)}
        for r in rows
    ]

    groups = []
    for members in cluster_near_duplicates(items, max_hamming):
        catalogs = sorted({m["catalog"] for m in members})
        members_sorted = sorted(m["id"] for m in members)
        groups.append(
            FindingGroup(
                finding_type="near_duplicate",
                finding_key=f"nd:{members_sorted[0]}",
                member_image_ids=members_sorted,
                member_catalogs=catalogs,
                n_products=len(catalogs),
                provenance_pair=provenance_pair([m["prov"] for m in members]),
                score=float(len(catalogs)),
                severity=severity_for(len(catalogs)),
                detail={"n_images": len(members), "max_hamming": max_hamming,
                        "signal": "perceptual_hash_cluster"},
            )
        )

    return write_findings(
        db, detector="tier1.near_duplicate", version=VERSION,
        params={"max_hamming": max_hamming, "hash": "phash64"},
        groups=groups, corpus_count=len(items), started_at=started,
    )


def run_all(db: Database) -> dict[str, int]:
    blobs = BlobStore(get_settings().blobs_dir)
    n_features = compute_features(db, blobs)
    return {
        "features_computed": n_features,
        "near_duplicate": detect_near_duplicate(db),
    }
