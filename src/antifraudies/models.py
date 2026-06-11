"""Normalized, vendor-agnostic record schema — the shared foundation for both phases.

Every vendor adapter emits exactly these types, so the evidence store and every phase-2
pipeline consume one schema regardless of which vendor a record came from. The schema is
designed for *cross-image* querying (whole-corpus comparison) and for later band-level
extraction, which is where the highest-value forensic signals live.

Framing discipline: these records describe captured evidence and parsed metadata only.
Nothing here asserts that any image is manipulated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .provenance import Provenance


class ProductRef(BaseModel):
    """A product to visit, produced by enumeration before any product page is fetched."""

    vendor: str
    catalog_number: str  # stable primary key
    product_url: str


class FilenameMetadata(BaseModel):
    """Metadata parsed out of an image filename — itself a forensic signal.

    Captured verbatim (``raw``) AND parsed: e.g. shared timestamps across unrelated
    products are a bookkeeping tell worth querying on later.
    """

    raw: str
    catalog_token: str | None = None
    target_token: str | None = None
    application_token: str | None = None
    advanced_verification_marker: bool = False  # an "AV" token appears in the filename
    timestamp_token: str | None = None  # verbatim timestamp string, e.g. "20200824211338"
    pubmed_id: str | None = None  # present on third-party (BenchSci) filenames


class VerificationImage(BaseModel):
    """One verification image as advertised on a product page, plus its capture record."""

    # Identity / linkage
    vendor: str
    catalog_number: str
    vendor_image_id: str | None = None  # the vendor's own image id (e.g. TF "imageId")

    # Provenance — never conflate internal vs third-party.
    provenance: Provenance
    provenance_disagreement: str | None = None  # set when classification signals conflicted
    source_type_raw: str | None = None  # the vendor's raw code, kept verbatim

    # Vendor-supplied descriptive metadata
    application_abbrev: str | None = None  # e.g. "WB"
    application_name: str | None = None  # e.g. "Western Blot"
    caption: str | None = None  # the long description
    short_caption: str | None = None
    title: str | None = None
    alt_tag: str | None = None
    journal_text: str | None = None  # populated for third-party published figures
    benchsci_pubmed_id: str | None = None  # source paper PMID for third-party images

    # Source locations
    image_filename: str  # verbatim filename
    image_url_full: str  # highest-resolution URL we capture
    image_url_variants: dict[str, str] = Field(default_factory=dict)  # size -> url

    # Parsed filename metadata
    filename_metadata: FilenameMetadata | None = None

    # Capture record (filled in once the image bytes are fetched). The image's source page
    # is the product page (join via catalog_number -> products.product_url); we record where
    # it came from, not a stored copy of the page itself.
    content_sha256: str | None = None
    byte_size: int | None = None
    content_type: str | None = None
    http_status: int | None = None
    captured_at: datetime | None = None


class Product(BaseModel):
    """A product (antibody) and its descriptive metadata."""

    vendor: str
    catalog_number: str  # stable primary key
    product_url: str
    product_name: str | None = None
    target: str | None = None
    clone: str | None = None
    rrid: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class ScrapeResult(BaseModel):
    """What an adapter returns for a single product page.

    We keep the product metadata and the per-image records (the rows that make cross-product
    image-reuse detectable); we deliberately do NOT retain the raw page HTML — the project
    cares about which images are reused/altered and where, not about archiving the page as
    litigation evidence.
    """

    product: Product
    images: list[VerificationImage]
