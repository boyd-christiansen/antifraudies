# antifraudies

Catalog-scale **forensic image-provenance** tooling for antibody-vendor "verification"
images.

Antibody vendors publish verification images (Western blots, immunofluorescence, etc.) on
product pages to convince scientists a product works. Independent researchers have
documented hundreds of these images in one major vendor's catalog showing signs of digital
manipulation — protein bands duplicated under flips and rotations, a single background
"template" reused across dozens of unrelated products, regions painted over, copy-pasted
noise, and whole images reused for two different products. Finding this by hand does not
scale. This project automates the **evidence-gathering and forensic-screening** of it.

> [!IMPORTANT]
> **Framing discipline — this system surfaces _apparent_ anomalies for human review. It
> never renders a verdict.** Nothing in this code, its output, or its naming asserts that
> any image is manipulated or fabricated. The deliverable is a ranked, evidence-backed
> queue for a qualified human to adjudicate.

## Two-phase plan

**Phase 1 — the scraper (implemented).** Enumerate a vendor's catalog, fetch verification
images and their metadata, record each image's **provenance**, and persist everything as
**preserved evidence** in a normalized, cross-image-queryable store.

**Phase 2 — the forensic pipeline (architected here, not built).** A cost-ordered funnel —
cheap operations on everything, expensive ones only on what survives — consuming the
phase-1 store:

1. metadata & filename analysis (cheap reuse / bookkeeping tells)
2. whole-image near-duplicate detection (one image reused across products)
3. background-template fingerprinting (one background reused across many products)
4. image segmentation (extract individual bands/regions)
5. cross-catalog band matching (bands copied/reused under flips/rotations)
6. single-image forensics (copy-pasted noise, painted-over regions, splice seams)
7. meta-scoring + human review queue (fuse signals, rank, overlay evidence)

The phase-1 store is the **shared foundation** every one of these consumes, which is why
its schema is built for cross-image querying and band-level extraction from day one. The
`pipelines/` and `review/` directories are documented placeholders for this work.

## Why provenance is central

Verification media is partitioned by who produced it, and the distinction is the entire
claim. For Thermo Fisher:

| `sourceType` | label | normalized provenance | corpus |
|---|---|---|---|
| 1 | Antibody Testing Data | `internal_testing_data` | **vendor's own data → forensic target** |
| 2 | Advanced Verification | `internal_advanced_verification` | **vendor's own data → forensic target** |
| 3 | Published Figures | `third_party_published_figure` | third-party, via **BenchSci** (`benchSciPubmedId` = source PMID) |

Internal data (the vendor's own) and third-party published figures are **tracked
separately and never conflated**: "the vendor fabricated this" and "the vendor reused a
published figure" are entirely different statements.

## How Thermo Fisher serves the data (confirmed)

- **Data is server-rendered into the product-page HTML** as an Angular `tfs-media-gallery`
  directive whose `media-items` attribute is a JS object grouping every image by provenance
  category, with full per-image metadata (four resolutions, caption, application, image id,
  verbatim filename, `sourceType`, `benchSciPubmedId`). No headless browser is needed today;
  a polite HTTP GET + parse suffices. The `VendorAdapter` interface keeps a
  headless/JSON-API fallback open for when markup changes or other (true-SPA) vendors are
  added.
- **Filenames encode metadata for free** (catalog #, target, application, an `AV` marker,
  timestamp) — captured verbatim **and** parsed, because e.g. shared timestamps across
  unrelated products are themselves a signal.
- **Enumeration is via the robots-allowed sitemaps**
  (`/antibody/sitemap-AntibodiesIndex.xml` → child product-page sitemaps). The search API is
  `robots.txt`-disallowed and is **not** used.

## Polite, defensible crawling

This work may be published, so the crawl must be above reproach:

- honest `User-Agent` token + `From` contact address (we do **not** disguise our identity);
- `robots.txt` fetched, parsed, and enforced (disallowed paths refused, `crawl-delay` honored);
- conservative per-host rate limiting with jitter and exponential backoff on 429/5xx;
- an on-disk HTTP cache so nothing is fetched twice;
- every capture preserved as evidence: **original bytes, content hash, source URL, provenance,
  caption, capture timestamp**, plus a full page-HTML snapshot and optional Wayback archival.

> The target sits behind Akamai, which rejects requests lacking realistic `Accept` headers.
> We send realistic `Accept`/`Accept-Language` headers but keep our identity honest in the UA
> token. If the honest UA is blocked at scale, that is a human decision to make, not
> something to silently evade.

## Evidence integrity

Original bytes and hashes are **never modified after capture**. Raw captures live under
`data/blobs/` (images) and `data/pages/` (HTML), content-addressed by SHA-256, each image
with a self-describing JSON sidecar. Derived/processed artifacts (phase 2) live separately,
never overwriting raw evidence.

## Repository layout

```
src/antifraudies/      # the package
  models.py            # normalized record schema (shared across phases)
  provenance.py        # provenance taxonomy + classifier
  store/               # SQLite (normalized records) + content-addressed blob store
  crawl/               # polite HTTP client, robots enforcement, optional Wayback archival
  adapters/            # per-vendor adapters -> one normalized schema (thermofisher first)
  scrape.py  cli.py    # orchestration + CLI
reference/zenodo/      # the documented-image set (DOI 10.5281/zenodo.20402475); manifest now, bytes in phase 2
pipelines/             # PHASE 2 placeholders (documented, empty)
review/                # PHASE 2 placeholder: human review queue tooling
seeds/                 # bounded seed lists for first runs
data/                  # runtime evidence store (gitignored)
tests/                 # parser / provenance / filename tests against real captured fixtures
```

## Quickstart

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                                                   # offline tests vs real fixtures

# List products from the sitemap (no pages fetched):
antifraudies enumerate --vendor thermofisher --limit 20

# Scrape a bounded seed politely and preserve evidence:
antifraudies scrape --vendor thermofisher --seed seeds/thermofisher_seed.txt

# Preview the cross-image queries phase 2 builds on:
antifraudies report --vendor thermofisher
```

Configuration lives in `config/default.toml` (override via `ANTIFRAUDIES_*` env vars).

## Status

Phase 1 (scraper) is implemented for Thermo Fisher. Phase 2 (image processing) is
**architected but intentionally not implemented** — see `pipelines/README.md`.
