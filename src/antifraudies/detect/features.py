"""Tier 1 image features — cheap, deterministic, computed once per image.

Loads each captured image from the content-addressed blob store and records:
  - perceptual hash (pHash) + difference hash (dHash)  -> near-duplicate / similar-image
  - width / height / is_grayscale                      -> routing + sanity
  - contrast_residual (global high-frequency energy)   -> a COARSE feature, not a verdict;
        the brushstroke/paint *localization* is a Tier-3 learned detector, not this scalar.

Idempotent: upserts into image_features keyed by image_id; re-running recomputes in place.
Embeddings (the pgvector column) are computed by a separate, heavier stage — see embeddings.py.
"""

from __future__ import annotations

import imagehash
import numpy as np
from PIL import Image

from ..store.blobs import BlobStore
from ..store.db import Database

VERSION = "0.1"
# Vendor verification images are small; disable Pillow's decompression-bomb guard.
Image.MAX_IMAGE_PIXELS = None


def _grayscale_and_contrast(img: Image.Image) -> tuple[bool, float]:
    rgb = np.asarray(img.convert("RGB"))
    is_gray = bool(
        np.array_equal(rgb[..., 0], rgb[..., 1]) and np.array_equal(rgb[..., 1], rgb[..., 2])
    )
    g = np.asarray(img.convert("L"), dtype=np.float64)
    if g.shape[0] < 3 or g.shape[1] < 3:
        return is_gray, 0.0
    # 4-neighbour Laplacian magnitude → global high-frequency energy (std).
    lap = np.abs(
        4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
    )
    return is_gray, float(lap.std())


def compute_features(db: Database, blobs: BlobStore, *, limit: int | None = None) -> int:
    """Compute features for images that have captured bytes but no features row yet."""
    q = """
        SELECT vi.id, vi.content_sha256
        FROM verification_images vi
        LEFT JOIN image_features f ON f.image_id = vi.id
        WHERE vi.content_sha256 IS NOT NULL AND f.image_id IS NULL
    """
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = db.conn.execute(q).fetchall()

    done = 0
    for r in rows:
        path = blobs.find(r["content_sha256"])
        if path is None:
            continue
        try:
            with Image.open(path) as img:
                img.load()
                w, h = img.size
                phash = str(imagehash.phash(img))
                dhash = str(imagehash.dhash(img))
                is_gray, contrast = _grayscale_and_contrast(img)
        except Exception:  # noqa: BLE001 — a corrupt image never aborts the batch
            continue

        db.conn.execute(
            """
            INSERT INTO image_features
                (image_id, phash, dhash, width, height, is_grayscale, contrast_residual,
                 detector_version)
            VALUES (%(image_id)s, %(phash)s, %(dhash)s, %(width)s, %(height)s,
                    %(is_grayscale)s, %(contrast_residual)s, %(version)s)
            ON CONFLICT (image_id) DO UPDATE SET
                phash = EXCLUDED.phash, dhash = EXCLUDED.dhash,
                width = EXCLUDED.width, height = EXCLUDED.height,
                is_grayscale = EXCLUDED.is_grayscale,
                contrast_residual = EXCLUDED.contrast_residual,
                detector_version = EXCLUDED.detector_version
            """,
            {
                "image_id": r["id"], "phash": phash, "dhash": dhash,
                "width": w, "height": h, "is_grayscale": is_gray,
                "contrast_residual": contrast, "version": VERSION,
            },
        )
        done += 1
        if done % 500 == 0:
            db.commit()
    db.commit()
    return done
