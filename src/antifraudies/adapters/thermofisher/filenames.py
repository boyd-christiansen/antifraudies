"""Parse forensic metadata out of Thermo Fisher image filenames.

Filenames encode catalog number, target, application, an "AV" (Advanced Verification)
marker, and a timestamp — for free. The timestamp is itself a forensic signal: the same
timestamp on images of unrelated products is a bookkeeping tell. We therefore capture the
filename verbatim AND parse it; we never discard it.

Observed naming variants (all handled, all covered by tests):
    MA5-12557-P53-WB-1-20241029_101909.jpg
    MA512557-Cellulartumorantigenp53-AV1-WB-20200824211338.jpg
    MA512557-P53-CRISPR-AV-WB.jpg                  (no timestamp)
    MA512557-p53-BM-WB_20251205132327.jpg
    p53-Antibody-MA5-12557-ChIP_20180402140757.jpg
    p53-Monoclonal-Antibody-MA5-12557-WB.jpg       (no timestamp)
    MA512557-28843151-p53-gr3(20468).jpg           (third-party, embeds a PubMed id)
    tfs_25237_biology-11-01719-g007.jpg            (third-party via BenchSci)
"""

from __future__ import annotations

import re

from ...models import FilenameMetadata

# Application / validation-type tokens that may appear in a filename. The authoritative
# application comes from the record's appAbv field; this is corroboration only.
_APP_TOKENS = {
    "WB", "ICC", "IF", "ICCIF", "IHC", "CHIP", "FLOW", "FC", "IP", "ELISA",
    "KD", "RE", "TM", "CRISPR", "BM",
}
_NOISE_TOKENS = {"ANTIBODY", "MONOCLONAL", "POLYCLONAL", "RECOMBINANT"}

# Catalog number, e.g. MA5-12557 or MA512557 (dash optional).
_CATALOG_RE = re.compile(r"\b([A-Z]{2,3}\d?-?\d{4,})\b", re.IGNORECASE)
# 14-digit (YYYYMMDDHHMMSS) or YYYYMMDD_HHMMSS timestamps.
_TIMESTAMP_RE = re.compile(r"(\d{8}_\d{6}|\d{14})")
# An "AV" marker token (AV, AV1, AV2 ...).
_AV_TOKEN_RE = re.compile(r"^AV\d*$", re.IGNORECASE)
# A standalone PubMed id (7-8 digits) — third-party legacy filenames.
_PMID_RE = re.compile(r"^\d{7,8}$")


def parse_filename(filename: str, *, catalog_hint: str | None = None) -> FilenameMetadata:
    meta = FilenameMetadata(raw=filename)

    stem = re.sub(r"\.(jpg|jpeg|png|gif|tif|tiff)$", "", filename, flags=re.IGNORECASE)
    paren = re.sub(r"\(.*?\)", "", stem)  # drop a trailing "(20468)"-style suffix

    # Timestamp (captured verbatim, then removed from the token stream).
    ts = _TIMESTAMP_RE.search(paren)
    if ts:
        meta.timestamp_token = ts.group(1)
        paren = paren.replace(ts.group(1), " ")

    # Third-party via BenchSci: tfs_<seq>_<journal-figure-id>. No catalog/app to trust.
    if stem.lower().startswith("tfs_"):
        return meta

    # Catalog number.
    cat = _CATALOG_RE.search(paren)
    if cat:
        meta.catalog_token = cat.group(1).upper()

    tokens = [t for t in re.split(r"[-_\s]+", paren) if t]
    remaining: list[str] = []
    for tok in tokens:
        up = tok.upper()
        if meta.catalog_token and up == meta.catalog_token:
            continue
        if _AV_TOKEN_RE.match(tok):
            meta.advanced_verification_marker = True
            continue
        if up in _APP_TOKENS and meta.application_token is None:
            meta.application_token = up
            continue
        if _PMID_RE.match(tok) and meta.pubmed_id is None:
            meta.pubmed_id = tok
            continue
        if up in _NOISE_TOKENS or tok.isdigit():
            continue
        remaining.append(tok)

    # Best-effort target: first surviving descriptive token.
    if remaining:
        meta.target_token = remaining[0]
    return meta
