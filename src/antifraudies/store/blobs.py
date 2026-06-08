"""Content-addressed blob store for raw evidence bytes.

Every captured artifact (image bytes, page HTML) is stored under its SHA-256 digest, so:
  - identical content is stored once (a natural whole-image-reuse signal), and
  - bytes are immutable: the path IS the hash, so a write either matches existing
    content or creates a new object. We never modify a blob after writing it.

Each image blob is written alongside a JSON sidecar holding the full normalized record
and capture metadata, so the raw evidence is self-describing on disk even without the DB.
"""

from __future__ import annotations

import hashlib
import json
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

    def write_sidecar(self, digest: str, record: dict) -> Path:
        """Write a JSON sidecar next to an image blob describing the capture."""
        path = self._path_for(digest, "json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        return path

    def path(self, digest: str, ext: str = "bin") -> Path:
        return self._path_for(digest, ext)

    def exists(self, digest: str, ext: str = "bin") -> bool:
        return self._path_for(digest, ext).exists()
