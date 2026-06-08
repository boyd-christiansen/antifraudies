"""Parser tests against the real ``media-items`` data island captured from MA5-12557."""

from antifraudies.adapters.thermofisher.parse import (
    parse_media_items,
    provenance_breakdown,
    record_to_image,
)
from antifraudies.provenance import Provenance

CATALOG = "MA5-12557"


def test_parses_all_records(media_items_value):
    records = parse_media_items(media_items_value)
    assert len(records) == 51  # the page advertises 51 verification images


def test_group_keys_present(media_items_value):
    keys = {k for k, _ in parse_media_items(media_items_value)}
    assert keys == {"Antibody Testing Data", "Advanced Verification", "Published Figures"}


def test_provenance_split(media_items_value):
    images = [
        record_to_image(g, r, catalog_number=CATALOG)
        for g, r in parse_media_items(media_items_value)
    ]
    counts = provenance_breakdown(images)
    assert counts[Provenance.INTERNAL_TESTING_DATA.value] == 16
    assert counts[Provenance.INTERNAL_ADVANCED_VERIFICATION.value] == 7
    assert counts[Provenance.THIRD_PARTY_PUBLISHED_FIGURE.value] == 28
    # 23 internal (forensic target) vs 28 third-party — never conflated.
    internal = sum(1 for i in images if i.provenance.is_internal)
    third = sum(1 for i in images if i.provenance.is_third_party)
    assert internal == 23
    assert third == 28


def test_caption_with_embedded_commas_survives(media_items_value):
    images = [
        record_to_image(g, r, catalog_number=CATALOG)
        for g, r in parse_media_items(media_items_value)
    ]
    bm = next(i for i in images if i.image_filename == "MA512557-p53-BM-WB_20251205132327.jpg")
    # The description is a long, comma-laden sentence; it must be captured whole.
    assert bm.caption is not None
    assert "," in bm.caption
    assert "SK-OV-3" in bm.caption
    assert len(bm.caption) > 200


def test_third_party_image_carries_pubmed_id(media_items_value):
    images = [
        record_to_image(g, r, catalog_number=CATALOG)
        for g, r in parse_media_items(media_items_value)
    ]
    tfs = next(i for i in images if i.image_filename.startswith("tfs_25237"))
    assert tfs.provenance.is_third_party
    assert tfs.benchsci_pubmed_id and tfs.benchsci_pubmed_id != "0"


def test_image_url_variants_captured(media_items_value):
    images = [
        record_to_image(g, r, catalog_number=CATALOG)
        for g, r in parse_media_items(media_items_value)
    ]
    sample = images[0]
    assert sample.image_url_full.startswith("https://www.thermofisher.com/antibody/images/")
    assert "full" in sample.image_url_variants


def test_fallback_parser_matches_record_count(media_items_value):
    # The tolerant fallback must also see every record (group key lost, sourceType kept).
    from antifraudies.adapters.thermofisher.parse import _records_via_fallback

    assert len(_records_via_fallback(media_items_value)) == 51
