"""Content-addressed blob store for image bytes.

Every image is stored under its SHA-256 digest, so:
  - identical content is stored once across the WHOLE catalog (the cheap whole-image-reuse
    signal: one image used on many products collapses to a single blob, while each listing
    still keeps its own row in the database), and
  - bytes are immutable: the path IS the hash, so a write either matches existing content
    or creates a new object. We never modify a blob after writing it.

The database is the single source of metadata; blobs hold only the pixels.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BlobStore:
    """A simple sharded content-addressed store rooted at ``root``.

    Objects are sharded by the first two hex chars of the digest to avoid huge flat
    directories at catalog scale: ``<root>/<ab>/<abcdef...>.<ext>``.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest: str, ext: str) -> Path:
        ext = ext.lstrip(".")
        shard = self.root / digest[:2]
        return shard / (f"{digest}.{ext}" if ext else digest)

    def put(self, data: bytes, ext: str = "bin") -> str:
        """Store ``data``; return its sha256. Idempotent — a re-put is a no-op."""
        digest = sha256_hex(data)
        path = self._path_for(digest, ext)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temp file then atomically rename, so a partial write never
            # masquerades as a complete, hash-named object.
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.rename(path)
        return digest

    def path(self, digest: str, ext: str = "bin") -> Path:
        return self._path_for(digest, ext)

    def exists(self, digest: str, ext: str = "bin") -> bool:
        return self._path_for(digest, ext).exists()

    def find(self, digest: str) -> Path | None:
        """Locate a stored blob by digest regardless of extension (jpg/png/...)."""
        shard = self.root / digest[:2]
        if not shard.is_dir():
            return None
        for p in shard.glob(f"{digest}.*"):
            if not p.name.endswith(".tmp"):
                return p
        return None
