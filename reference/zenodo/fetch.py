"""Record the Zenodo documented-image set's manifest.

Phase 1 scope: fetch and store the Zenodo record's *metadata and file listing* only.
Downloading the image bytes is deferred to phase 2 and gated behind
``[zenodo] download_bytes`` in config — see this directory's README for the rationale.

Usage:
    python reference/zenodo/fetch.py            # writes manifest.json beside this file
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
# Zenodo concept DOI 10.5281/zenodo.20402475 -> records API. The concept id is the numeric
# suffix; the API resolves it to the latest version.
ZENODO_API = "https://zenodo.org/api/records/20402475"


def fetch_manifest() -> dict:
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        resp = client.get(ZENODO_API, headers={"Accept": "application/json"})
        resp.raise_for_status()
        record = resp.json()

    files = record.get("files", [])
    return {
        "doi": record.get("doi"),
        "title": record.get("metadata", {}).get("title"),
        "version": record.get("metadata", {}).get("version"),
        "publication_date": record.get("metadata", {}).get("publication_date"),
        "file_count": len(files),
        "files": [
            {
                "key": f.get("key"),
                "size": f.get("size"),
                "checksum": f.get("checksum"),
                "link": f.get("links", {}).get("self"),
            }
            for f in files
        ],
        "note": "Manifest only. Image bytes are downloaded in phase 2 "
        "(config [zenodo] download_bytes = true). These are external, third-party "
        "annotations — labeled positives for validation, NOT ground truth inside this system.",
    }


def main() -> None:
    manifest = fetch_manifest()
    out = HERE / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out} — {manifest['file_count']} files listed (bytes deferred to phase 2).")


if __name__ == "__main__":
    main()
