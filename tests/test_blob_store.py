"""Tests for antifraudies.store.blobs.BlobStore."""

from __future__ import annotations

import hashlib

from antifraudies.store.blobs import BlobStore


def test_put_returns_sha256(tmp_path):
    """put() returns the hex SHA-256 digest of the stored data."""
    store = BlobStore(tmp_path / "blobs")
    data = b"hello world"
    digest = store.put(data)
    assert digest == hashlib.sha256(data).hexdigest()


def test_put_deduplication(tmp_path):
    """Storing the same content twice returns the same digest and creates only one file."""
    store = BlobStore(tmp_path / "blobs")
    data = b"duplicate me"
    d1 = store.put(data)
    d2 = store.put(data)
    assert d1 == d2
    # Only one blob file on disk (in the shard directory).
    shard = tmp_path / "blobs" / d1[:2]
    blob_files = [f for f in shard.iterdir() if not f.name.endswith(".tmp")]
    assert len(blob_files) == 1


def test_put_different_content(tmp_path):
    """Different payloads produce different digests."""
    store = BlobStore(tmp_path / "blobs")
    d1 = store.put(b"alpha")
    d2 = store.put(b"bravo")
    assert d1 != d2


def test_sharded_directory_structure(tmp_path):
    """Blobs are stored under <root>/<first-2-hex>/<full-digest>.<ext>."""
    store = BlobStore(tmp_path / "blobs")
    data = b"shard check"
    digest = store.put(data, ext="bin")

    expected = tmp_path / "blobs" / digest[:2] / f"{digest}.bin"
    assert expected.exists()
    assert expected.read_bytes() == data


def test_exists_true_and_false(tmp_path):
    """exists() returns True after put and False for an unknown digest."""
    store = BlobStore(tmp_path / "blobs")
    digest = store.put(b"some bytes")
    assert store.exists(digest) is True
    assert store.exists("0" * 64) is False


def test_find_locates_blob(tmp_path):
    """find() returns the stored path for a known digest."""
    store = BlobStore(tmp_path / "blobs")
    data = b"findable"
    digest = store.put(data, ext="png")
    found = store.find(digest)
    assert found is not None
    assert found.read_bytes() == data


def test_find_returns_none_for_missing(tmp_path):
    """find() returns None when no blob with that digest exists."""
    store = BlobStore(tmp_path / "blobs")
    assert store.find("0" * 64) is None


def test_find_ignores_tmp_files(tmp_path):
    """find() skips .tmp files that may be left behind by interrupted writes."""
    store = BlobStore(tmp_path / "blobs")
    fake_digest = "ab" + "0" * 62
    shard = tmp_path / "blobs" / fake_digest[:2]
    shard.mkdir(parents=True, exist_ok=True)
    # Plant a .tmp file that looks like a blob.
    tmp_file = shard / f"{fake_digest}.bin.tmp"
    tmp_file.write_bytes(b"incomplete")

    assert store.find(fake_digest) is None


def test_put_different_extensions(tmp_path):
    """put() with different extensions stores under the correct filenames."""
    store = BlobStore(tmp_path / "blobs")
    data = b"image data"
    digest_jpg = store.put(data, ext="jpg")
    digest_png = store.put(data, ext="png")

    # Same content → same digest regardless of extension.
    assert digest_jpg == digest_png

    # Both extension paths should resolve correctly via .path().
    assert store.path(digest_jpg, ext="jpg").name.endswith(".jpg")
    assert store.path(digest_png, ext="png").name.endswith(".png")
