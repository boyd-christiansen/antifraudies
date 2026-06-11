-- Normalized store (PostgreSQL + pgvector). Shared foundation for phase 1 (scrape) and
-- phase 2 (forensic detectors). Raw image BYTES live in the content-addressed filesystem
-- blob store, not here; this database holds queryable records, derived features (incl.
-- embeddings), and findings. Image bytes are immutable once written.
--
-- We do NOT store source page HTML: the project cares about which images are reused or
-- altered and where, not about archiving pages. An image's source page is its product page
-- (join via catalog_number -> products.product_url).

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================ phase 1: scrape

CREATE TABLE IF NOT EXISTS products (
    vendor          TEXT NOT NULL,
    catalog_number  TEXT NOT NULL,           -- stable primary key within a vendor
    product_url     TEXT NOT NULL,
    product_name    TEXT,
    target          TEXT,
    clone           TEXT,
    rrid            TEXT,
    first_seen      TIMESTAMPTZ,
    last_seen       TIMESTAMPTZ,
    PRIMARY KEY (vendor, catalog_number)
);

CREATE TABLE IF NOT EXISTS verification_images (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vendor                  TEXT NOT NULL,
    catalog_number          TEXT NOT NULL,
    vendor_image_id         TEXT,

    -- Provenance: never conflate internal (forensic target) vs third-party.
    provenance              TEXT NOT NULL,
    provenance_disagreement TEXT,
    source_type_raw         TEXT,

    -- Rendered modality (which forensics apply): separate axis from the assay below.
    modality                TEXT,
    modality_confidence     TEXT,

    -- Vendor descriptive metadata
    application_abbrev      TEXT,
    application_name        TEXT,
    caption                 TEXT,
    short_caption           TEXT,
    title                   TEXT,
    alt_tag                 TEXT,
    journal_text            TEXT,
    benchsci_pubmed_id      TEXT,

    -- Source locations
    image_filename          TEXT NOT NULL,    -- verbatim
    image_url_full          TEXT NOT NULL,
    image_url_variants      JSONB,

    -- Parsed filename metadata (a forensic signal in its own right)
    fn_catalog              TEXT,
    fn_target               TEXT,
    fn_application          TEXT,
    fn_av_marker            INTEGER,
    fn_timestamp            TEXT,
    fn_pubmed_id            TEXT,

    -- Capture record
    content_sha256          TEXT,             -- points at data/blobs/<sha>.<ext>; NULL until fetched
    byte_size               BIGINT,
    content_type            TEXT,
    http_status             INTEGER,
    captured_at             TIMESTAMPTZ,

    UNIQUE (vendor, catalog_number, image_filename),
    FOREIGN KEY (vendor, catalog_number) REFERENCES products(vendor, catalog_number)
);

CREATE INDEX IF NOT EXISTS idx_images_content_sha  ON verification_images(content_sha256);
CREATE INDEX IF NOT EXISTS idx_images_fn_timestamp ON verification_images(fn_timestamp);
CREATE INDEX IF NOT EXISTS idx_images_provenance   ON verification_images(provenance);
CREATE INDEX IF NOT EXISTS idx_images_modality     ON verification_images(modality);
CREATE INDEX IF NOT EXISTS idx_images_pubmed       ON verification_images(benchsci_pubmed_id);
CREATE INDEX IF NOT EXISTS idx_images_catalog      ON verification_images(vendor, catalog_number);

-- ====================================================== phase 2: derived data

-- One row of derived features per image (Tier 1). The embedding column is pgvector;
-- DINOv2 ViT-S/14 = 384 dims (kept NULL until the embedding stage runs).
CREATE TABLE IF NOT EXISTS image_features (
    image_id            BIGINT PRIMARY KEY REFERENCES verification_images(id) ON DELETE CASCADE,
    phash               TEXT,                 -- perceptual hash (hex)
    dhash               TEXT,                 -- difference hash (hex)
    width               INTEGER,
    height              INTEGER,
    is_grayscale        BOOLEAN,
    contrast_residual   REAL,                 -- cheap "painted-over"/brushstroke flag stat
    embedding           vector(384),
    detector_version    TEXT,
    params_hash         TEXT,
    created_at          TIMESTAMPTZ DEFAULT now()
);
-- ANN index for embedding similarity (cosine). Harmless while embeddings are NULL.
CREATE INDEX IF NOT EXISTS idx_features_embedding
    ON image_features USING hnsw (embedding vector_cosine_ops);

-- The queryable, append-only output. A finding groups the images implicated by one signal.
-- (finding_type, finding_key) is the deterministic identity so detector re-runs are idempotent.
CREATE TABLE IF NOT EXISTS findings (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    finding_type        TEXT NOT NULL,        -- whole_image_reuse | metadata_reuse | near_duplicate | ...
    finding_key         TEXT NOT NULL,
    score               REAL,
    severity            TEXT,
    n_products          INTEGER,
    member_image_ids    BIGINT[],
    member_catalogs     TEXT[],
    provenance_pair     TEXT,                 -- internal-internal | internal-third_party | ...
    detail              JSONB,
    evidence_ref        TEXT,
    detector            TEXT,
    detector_version    TEXT,
    params_hash         TEXT,
    status              TEXT DEFAULT 'pending',
    created_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (finding_type, finding_key)
);
CREATE INDEX IF NOT EXISTS idx_findings_type  ON findings(finding_type);
CREATE INDEX IF NOT EXISTS idx_findings_score ON findings(score DESC);

-- Reproducibility log: one row per detector execution.
CREATE TABLE IF NOT EXISTS detector_runs (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    detector            TEXT NOT NULL,
    version             TEXT,
    params              JSONB,
    corpus_count        INTEGER,
    findings_written    INTEGER,
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ DEFAULT now(),
    notes               TEXT
);
