-- Normalized store (SQLite). Shared foundation for phase 1 (scrape) and phase 2 (forensic
-- pipelines). Raw image BYTES live in the content-addressed filesystem blob store, not
-- here; this database holds the queryable normalized records and points at image blobs by
-- sha256. Image bytes are immutable once written.
--
-- We do NOT store the source page HTML: the project cares about which images are reused or
-- altered and where, not about archiving pages. An image's source page is its product page
-- (join via catalog_number -> products.product_url).
--
-- Schema is shaped for CROSS-IMAGE querying (whole-corpus comparison), which is where the
-- highest-value forensic signals live, and for later band-level extraction.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    vendor          TEXT NOT NULL,
    catalog_number  TEXT NOT NULL,           -- stable primary key within a vendor
    product_url     TEXT NOT NULL,
    product_name    TEXT,
    target          TEXT,
    clone           TEXT,
    rrid            TEXT,
    first_seen      TEXT,                     -- ISO-8601 UTC
    last_seen       TEXT,
    PRIMARY KEY (vendor, catalog_number)
);

CREATE TABLE IF NOT EXISTS verification_images (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor                  TEXT NOT NULL,
    catalog_number          TEXT NOT NULL,
    vendor_image_id         TEXT,

    -- Provenance: never conflate internal (forensic target) vs third-party.
    provenance              TEXT NOT NULL,
    provenance_disagreement TEXT,
    source_type_raw         TEXT,

    -- Rendered modality (blot_gel / microscopy / plot_chart / composite_panel / unknown):
    -- determines which forensics apply. Separate axis from the assay/application below.
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
    image_url_variants      TEXT,             -- JSON object: size -> url

    -- Parsed filename metadata (a forensic signal in its own right)
    fn_catalog              TEXT,
    fn_target               TEXT,
    fn_application          TEXT,
    fn_av_marker            INTEGER,          -- 0/1
    fn_timestamp            TEXT,             -- verbatim timestamp token
    fn_pubmed_id            TEXT,

    -- Capture record
    content_sha256          TEXT,             -- points at data/blobs/<sha>.<ext>; NULL until bytes fetched
    byte_size               INTEGER,
    content_type            TEXT,
    http_status             INTEGER,
    captured_at             TEXT,

    -- Identity for idempotent upsert: a given vendor image on a given product.
    UNIQUE (vendor, catalog_number, image_filename),
    FOREIGN KEY (vendor, catalog_number) REFERENCES products(vendor, catalog_number)
);

-- Indexes that anticipate phase-2 cross-image queries.
CREATE INDEX IF NOT EXISTS idx_images_content_sha   ON verification_images(content_sha256); -- whole-image reuse
CREATE INDEX IF NOT EXISTS idx_images_fn_timestamp  ON verification_images(fn_timestamp);   -- shared-timestamp tell
CREATE INDEX IF NOT EXISTS idx_images_provenance    ON verification_images(provenance);     -- partition by provenance
CREATE INDEX IF NOT EXISTS idx_images_modality      ON verification_images(modality);        -- route by rendered modality
CREATE INDEX IF NOT EXISTS idx_images_pubmed        ON verification_images(benchsci_pubmed_id);
CREATE INDEX IF NOT EXISTS idx_images_catalog       ON verification_images(vendor, catalog_number);
