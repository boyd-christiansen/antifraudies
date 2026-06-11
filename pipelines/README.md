# Phase 2 — forensic pipelines (design home)

> [!IMPORTANT]
> This directory documents the phase-2 **design** (the cost-ordered funnel below). The
> runnable detector code lives in the package at `src/antifraudies/detect/` so it can import
> the store and be tested. Phase 2 surfaces *apparent* anomalies for human review; it never
> renders a verdict.
>
> **Built so far:** Tier 0 — `metadata_reuse`, `whole_image_reuse` (`detect/tier0.py`);
> Tier 1 — image features + `near_duplicate` (`detect/features.py`, `detect/tier1.py`).
> Findings land in the `findings` table; run with `antifraudies detect --tier all`.
> **Next:** pgvector embeddings + ANN, then Tiers 2–3 (segmentation, band matching, learned
> splice/inpaint), then scoring/review.

Phase 2 is a **cost-ordered funnel**: cheap operations run on the whole corpus, expensive
operations run only on what survives upstream filtering. Every stage reads from and writes
back to the shared phase-1 evidence store (`src/antifraudies/store/`), keyed by the same
normalized schema. The highest-value signals are **cross-image** (one image, band, or
background reused across many products), so stages operate over the corpus as a queryable
whole — never one image in isolation.

| Stage (directory) | Question it answers | Cost |
|---|---|---|
| `metadata_analysis/` | Do filenames/metadata reveal reuse or bookkeeping tells (e.g. shared timestamps across unrelated products)? | cheap, runs on all |
| `near_duplicate/` | Is a whole image reused across products (incl. for a *different* antibody)? | cheap (perceptual hashing) |
| `background_fingerprint/` | Is one background "template" reused across many products with only a band edited in? | medium |
| `segmentation/` | Extract individual bands / regions from each blot. | medium |
| `band_matching/` | Is a band copied/reused under flip/rotation, across the catalog? Treats extracted bands as a DB searched against itself. | expensive, survivors only |
| `single_image_forensics/` | Within one image: copy-pasted noise, painted-over regions, splice seams. | expensive, survivors only |
| `scoring/` | Fuse all signals into a ranked, evidence-overlaid review queue for `../review/`. | cheap |

## Why the phase-1 store already supports this

- Provenance is recorded per image, so internal (forensic-target) and third-party corpora
  are never conflated.
- Raw bytes are content-addressed by SHA-256 — whole-image reuse falls out of a hash join;
  near-duplicate/band hashes can be added as new indexed columns/tables without reorganizing.
- Filename metadata (timestamps, application, AV markers) is parsed and indexed for the
  cheap first-pass filters.
- Derived artifacts (segmented bands, fingerprints, scores) live here under `pipelines/`,
  **separate from** the immutable raw captures.

## Validation data

The documented-image set in `../reference/zenodo/` is the intended labeled-positive
benchmark for tuning and evaluating these detectors.
