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
images and their metadata, record each image's **provenance**, and persist the image bytes
and metadata in a normalized, cross-image-queryable store.

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

## Three independent axes (not one label)

An image's **assay** (`application`: WB, IHC, Flow…), its **rendered modality**, and its
**provenance** are independent — and only the *rendered modality* decides which forensics
apply. A "WB" entry may be a photographic blot OR a bar chart quantifying it; "ChIP" may be
a gel or a microplate graph. So each image is also tagged with a `modality`:

| modality | examples | forensics that apply |
|---|---|---|
| `blot_gel` | Western blot, KD/KO/treatment westerns | **primary target**: band segmentation + cross-catalog matching, background reuse, copy-move, splice |
| `microscopy` | ICC/IF, IHC | copy-move, splice, reuse (no band extraction) |
| `plot_chart` | flow histograms, relative-expression bars, qPCR | **whole-image reuse only** — rendered from data, no pixel-band forensics |
| `composite_panel` | multi-panel paper figures | split into sub-panels, then route each |

Classification is a cheap **metadata prior** (`appAbv` + caption keywords) that tags the
whole catalog for free; a later image-feature pass and a VLM on the ambiguous tail confirm
it. `modality_confidence` marks the images that need that second look. So the pipeline is
*route-by-modality, then run only the applicable detectors* — e.g. the internal `blot_gel`
images are the high-value band-forensics corpus; charts get near-dup only.

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

## Crawling: fast, but defensible

The full antibody catalog is ~261K products (~1M requests including images). We crawl it in
**well under a day** — measured ~30 requests/s at concurrency 48 → ~9 hours — by running
many requests in flight over HTTP/2 with no fixed inter-request delay. Fast is not the same
as abusive:

- honest `User-Agent` token + `From` contact address (we do **not** disguise our identity);
- `robots.txt` fetched, parsed, and enforced (disallowed paths refused, `crawl-delay` honored);
- **adaptive backoff**: exponential backoff with jitter on 429/5xx — if the server signals
  stress, we yield; concurrency is configurable (`--concurrency`) to dial pressure up or down;
- we keep, per image: **original bytes + content hash, the source product URL, provenance,
  caption, application, filename metadata, and capture timestamp**.

> The target sits behind Akamai, which rejects requests lacking realistic `Accept` headers.
> We send realistic `Accept`/`Accept-Language` headers but keep our identity honest in the UA
> token. Sustained aggressive crawling may trip edge throttling; the backoff adapts, and
> concurrency is a knob — how hard to push is a human decision, not something to silently evade.

## What we keep (and what we don't)

The project's question is *which images are reused or altered, and where* — not archiving
pages as litigation evidence. So we deliberately keep the data lean:

- **Image bytes** — content-addressed by SHA-256 under `data/blobs/`, **immutable** after
  capture, and **deduped across the whole catalog** (one image used on N products collapses
  to a single blob, while each listing keeps its own database row).
- **Metadata rows** — products and per-image records in SQLite; this is the single source of
  metadata and the substrate for every cross-image query.
- We do **not** store raw page HTML or per-image JSON sidecars, and there is no external
  archival step. (Earlier drafts did; it added ~180 GB of page HTML for no analytic gain.)

Net storage for the full catalog is roughly **~60–80 GB of image bytes + a few GB of SQLite**,
versus ~250 GB before. Derived/processed artifacts (phase 2) live separately under
`pipelines/`, never overwriting raw image bytes.

## Repository layout

```
src/antifraudies/      # the package
  models.py            # normalized record schema (shared across phases)
  provenance.py        # provenance taxonomy + classifier
  store/               # SQLite (metadata records) + content-addressed image blob store
  crawl/               # HTTP/2 client (concurrent, adaptive backoff) + robots enforcement
  adapters/            # per-vendor adapters -> one normalized schema (thermofisher first)
  scrape.py  cli.py    # concurrent orchestration + CLI
reference/zenodo/      # the documented-image set (DOI 10.5281/zenodo.20402475); manifest now, bytes in phase 2
pipelines/             # PHASE 2 placeholders (documented, empty)
review/                # PHASE 2 placeholder: human review queue tooling
seeds/                 # bounded seed lists for first runs
data/                  # runtime store: image blobs + SQLite (gitignored)
tests/                 # parser / provenance / filename tests against real captured fixtures
```

## Quickstart

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                                                   # offline tests vs real fixtures

# List products from the sitemap (no pages fetched):
antifraudies enumerate --vendor thermofisher --limit 20

# Scrape a bounded seed (image bytes + metadata):
antifraudies scrape --vendor thermofisher --seed seeds/thermofisher_seed.txt

# Crawl the full catalog concurrently (raise -c to go faster):
antifraudies scrape --vendor thermofisher --concurrency 48

# Preview the cross-image queries phase 2 builds on:
antifraudies report --vendor thermofisher
```

Configuration lives in `config/default.toml` (override via `ANTIFRAUDIES_*` env vars).

## Status

Phase 1 (scraper) is implemented for Thermo Fisher. Phase 2 (image processing) is
**architected but intentionally not implemented** — see `pipelines/README.md`.
