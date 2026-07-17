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

import contextlib
import logging

import imagehash
import numpy as np
from PIL import Image

from ..store.blobs import BlobStore
from ..store.db import Database

log = logging.getLogger(__name__)

VERSION = "0.1"

# Default Pillow decompression-bomb threshold.  We raise it temporarily inside
# compute_features() rather than disabling it globally — see _max_pixels_override().
_DEFAULT_MAX_PIXELS = Image.MAX_IMAGE_PIXELS


@contextlib.contextmanager
def _max_pixels_override(limit: int | None = None):
    """Temporarily set ``Image.MAX_IMAGE_PIXELS``.

    Vendor verification images are small, but Pillow's default threshold can
    reject some legitimate large composite panels.  We scope the override to
    feature computation only so the rest of the process retains the guard.
    """
    prev = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = limit
    try:
        yield
    finally:
        Image.MAX_IMAGE_PIXELS = prev


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
    log.info("computing features for %d images", len(rows))

    done = 0
    for r in rows:
        path = blobs.find(r["content_sha256"])
        if path is None:
            log.debug("blob not found for sha256=%s (image_id=%s)", r["content_sha256"], r["id"])
            continue
        try:
            with _max_pixels_override(limit=None):
                with Image.open(path) as img:
                    img.load()
                    w, h = img.size
                    phash = str(imagehash.phash(img))
                    dhash = str(imagehash.dhash(img))
                    is_gray, contrast = _grayscale_and_contrast(img)
        except Exception as exc:  # noqa: BLE001 — a corrupt image never aborts the batch
            log.warning("feature extraction failed for %s: %s", path.name, exc)
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
            log.info("  ... %d / %d features computed", done, len(rows))
    db.commit()
    log.info("feature computation complete: %d images processed", done)
    return done
