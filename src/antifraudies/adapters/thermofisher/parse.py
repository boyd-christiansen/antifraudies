"""Parse a Thermo Fisher antibody product page.

The verification-image data is server-rendered into the HTML as an Angular directive
attribute on a ``tfs-media-gallery`` element:

    <div class="gal-cntr container" tfs-media-gallery
         sku="'MA5-12557'"
         media-items="{'Antibody Testing Data':[{...},...],
                       'Published Figures':[...],
                       'Advanced Verification':[...]}">

The ``media-items`` value is a JavaScript object literal: single-quoted strings, JS
``\\u00xx`` escapes, escaped apostrophes (``\\'``). It is *almost* JSON. We convert it to
JSON by protecting escaped apostrophes, swapping the structural single quotes for double
quotes, and ``json.loads``-ing the result (verified safe here: the value contains no raw
double quotes). If that ever fails on a future page, we fall back to a tolerant
per-record field extractor rather than losing the whole page.

This embedded-data path needs no headless browser today. The VendorAdapter interface
keeps a headless/JSON-API fallback open if the markup changes or Akamai blocks at scale.
"""

from __future__ import annotations

import json
import re

from ...modality import classify_modality
from ...models import Product, VerificationImage
from ...provenance import Provenance, classify_thermofisher
from .filenames import parse_filename

VENDOR = "thermofisher"

_MEDIA_ITEMS_RE = re.compile(r'media-items="([^"]*)"', re.DOTALL)
_PRODUCT_NAME_RE = re.compile(r"productName\s*=\s*'([^']{1,200})'")
_RRID_RE = re.compile(r"(RRID:\s*)?(AB_\d+)", re.IGNORECASE)
# The clone is the trailing parenthetical of a monoclonal's product name, e.g.
# "p53 Monoclonal Antibody (DO-7)" -> "DO-7". This is far more reliable than scanning the
# page for the word "clone", which collides with competitor clones named in captions.
_CLONE_IN_NAME_RE = re.compile(r"\(([A-Za-z0-9][A-Za-z0-9 .\-/]{0,30})\)\s*$")
_RECORD_RE = re.compile(r"\{'sku':.*?'benchSciPubmedId':'[^']*'\}", re.DOTALL)


# ---------------------------------------------------------------- data island

def extract_media_items(html: str) -> str | None:
    m = _MEDIA_ITEMS_RE.search(html)
    return m.group(1) if m else None


def _js_object_to_python(value: str) -> dict:
    """Convert the single-quoted JS object literal to a Python object via JSON."""
    sentinel = "\x00"  # cannot occur in the textual attribute value
    protected = value.replace("\\'", sentinel)  # protect literal apostrophes
    jsonish = protected.replace("'", '"')  # structural quotes -> JSON
    jsonish = jsonish.replace(sentinel, "'")  # restore apostrophes (valid inside JSON strings)
    return json.loads(jsonish)


def _records_via_fallback(value: str) -> list[tuple[str | None, dict]]:
    """Tolerant fallback: pull each record's known fields by regex if JSON parse fails.

    Loses the group key (we rely on each record's own sourceType for provenance), but
    never loses the whole page to one malformed field.
    """
    records: list[tuple[str | None, dict]] = []
    field_re = re.compile(r"'([A-Za-z]+)':(?:'((?:\\'|[^'])*)'|(true|false))")
    for chunk in _RECORD_RE.findall(value):
        rec: dict = {}
        for key, sval, bval in field_re.findall(chunk):
            if bval:
                rec[key] = bval == "true"
            else:
                rec[key] = sval.replace("\\'", "'")
        if rec:
            records.append((None, rec))
    return records


def parse_media_items(value: str) -> list[tuple[str | None, dict]]:
    """Return ``[(group_key, record_dict), ...]`` for every image on the page."""
    try:
        obj = _js_object_to_python(value)
    except (json.JSONDecodeError, ValueError):
        return _records_via_fallback(value)

    out: list[tuple[str | None, dict]] = []
    for group_key, records in obj.items():
        if isinstance(records, list):
            for rec in records:
                if isinstance(rec, dict):
                    out.append((group_key, rec))
    return out


# ------------------------------------------------------------------- mapping

def record_to_image(
    group_key: str | None, rec: dict, *, catalog_number: str
) -> VerificationImage:
    image_name = rec.get("imageName") or _basename(
        rec.get("imageUrlFullSize") or rec.get("imageUrl", "")
    )
    benchsci_pmid = _str_or_none(rec.get("benchSciPubmedId"))

    prov = classify_thermofisher(
        source_type=_str_or_none(rec.get("sourceType")),
        group_key=group_key,
        benchsci_pubmed_id=benchsci_pmid,
        image_filename=image_name,
    )
    mod = classify_modality(
        application_abbrev=_str_or_none(rec.get("appAbv")),
        application_name=_str_or_none(rec.get("appName")),
        caption=_str_or_none(rec.get("description")),
    )

    variants = {
        size: rec[key]
        for size, key in (
            ("full", "imageUrlFullSize"),
            ("mid", "imageUrlMidSize"),
            ("small", "imageUrlSmallSize"),
        )
        if rec.get(key)
    }
    full = rec.get("imageUrlFullSize") or rec.get("imageUrl") or ""

    return VerificationImage(
        vendor=VENDOR,
        catalog_number=catalog_number,
        vendor_image_id=_str_or_none(rec.get("imageId")),
        provenance=prov.provenance,
        provenance_disagreement=prov.disagreement,
        source_type_raw=_str_or_none(rec.get("sourceType")),
        modality=mod.modality,
        modality_confidence=mod.confidence,
        application_abbrev=_str_or_none(rec.get("appAbv")),
        application_name=_str_or_none(rec.get("appName")),
        caption=_str_or_none(rec.get("description")),
        short_caption=_str_or_none(rec.get("shortDescription")),
        title=_str_or_none(rec.get("title")),
        alt_tag=_str_or_none(rec.get("altTag")),
        journal_text=_str_or_none(rec.get("journalText")) or None,
        benchsci_pubmed_id=benchsci_pmid,
        image_filename=image_name,
        image_url_full=full,
        image_url_variants=variants,
        filename_metadata=parse_filename(image_name, catalog_hint=catalog_number),
    )


# --------------------------------------------------------------- product meta

def parse_product_metadata(html: str, *, catalog_number: str, product_url: str) -> Product:
    name = _search(_PRODUCT_NAME_RE, html)
    rrid_m = _RRID_RE.search(html)
    rrid = f"RRID:{rrid_m.group(2)}" if rrid_m else None
    clone = _clone_from_name(name)
    return Product(
        vendor=VENDOR,
        catalog_number=catalog_number,
        product_url=product_url,
        product_name=name,
        target=_target_from_name(name),
        clone=clone,
        rrid=rrid,
    )


def parse_product_page(
    html: str, *, catalog_number: str, product_url: str
) -> tuple[Product, list[VerificationImage]]:
    product = parse_product_metadata(html, catalog_number=catalog_number, product_url=product_url)
    images: list[VerificationImage] = []
    value = extract_media_items(html)
    if value:
        for group_key, rec in parse_media_items(value):
            images.append(record_to_image(group_key, rec, catalog_number=catalog_number))
    return product, images


def provenance_breakdown(images: list[VerificationImage]) -> dict[str, int]:
    counts: dict[str, int] = {p.value: 0 for p in Provenance}
    for img in images:
        counts[img.provenance.value] += 1
    return counts


# ----------------------------------------------------------------- helpers

def _basename(url: str) -> str:
    return url.split("?")[0].rsplit("/", 1)[-1]


def _str_or_none(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _search(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _clone_from_name(name: str | None) -> str | None:
    if not name or "polyclonal" in name.lower():
        return None  # polyclonals have no clone designation
    m = _CLONE_IN_NAME_RE.search(name)
    return m.group(1).strip() if m else None


def _target_from_name(name: str | None) -> str | None:
    if not name:
        return None
    # "p53 Monoclonal Antibody (DO-7)" -> "p53"
    head = re.split(r"\b(Monoclonal|Polyclonal|Recombinant|Antibody)\b", name)[0]
    return head.strip() or None
