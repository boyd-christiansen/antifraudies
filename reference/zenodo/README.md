# Documented problematic-image set (Zenodo)

**DOI:** [10.5281/zenodo.20402475](https://doi.org/10.5281/zenodo.20402475)
**Maintainers:** Reese Richardson & Sholto David
**What it is:** a curated, annotated, publicly contributed set of antibody-vendor
verification images the authors have flagged as problematic — effectively a set of
**labeled positive examples**: the cases a detector should eventually catch.

## How this project uses it

In **phase 2** this set is a likely source of **validation / tuning data**: a held-out
benchmark for the near-duplicate, background-fingerprint, band-matching, and single-image
forensics detectors, and a library of reference images to compare live captures against.

In **phase 1 (now)** we deliberately do **not** download its image bytes. Two reasons:

1. **Keep evidence streams separate.** Phase 1 builds a clean record of what the vendor
   serves *today*. Mixing in an external set of already-flagged positives would blur "what
   we independently captured" with "what someone else already concluded."
2. **Defer cost to when it pays off.** The bytes matter when detectors exist to consume
   them. Until then we only need to know the set exists and what it contains.

So `fetch.py` records the **manifest** (the Zenodo record's metadata and file listing) into
this directory and stops there. Downloading bytes is gated behind
`config/default.toml [zenodo] download_bytes = true` and intended for phase 2.

## Provenance note

When this set *is* ingested, its records must be tagged as **external reference /
third-party documentation**, never merged into the vendor-captured `verification_images`
corpus, and never treated as ground-truth "manipulation confirmed" inside this system — it
records others' annotations, which remain claims for human adjudication.
