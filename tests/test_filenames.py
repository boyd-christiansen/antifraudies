import pytest

from antifraudies.adapters.thermofisher.filenames import parse_filename


@pytest.mark.parametrize(
    "filename,expect",
    [
        (
            "MA5-12557-P53-WB-1-20241029_101909.jpg",
            {"application_token": "WB", "timestamp_token": "20241029_101909", "av": False},
        ),
        (
            "MA512557-Cellulartumorantigenp53-AV1-WB-20200824211338.jpg",
            {"application_token": "WB", "timestamp_token": "20200824211338", "av": True},
        ),
        (
            "MA512557-P53-CRISPR-AV-WB.jpg",
            {"application_token": "CRISPR", "timestamp_token": None, "av": True},
        ),
        (
            "MA512557-p53-BM-WB_20251205132327.jpg",
            {"application_token": "BM", "timestamp_token": "20251205132327", "av": False},
        ),
        (
            "p53-Antibody-MA5-12557-ChIP_20180402140757.jpg",
            {"application_token": "CHIP", "timestamp_token": "20180402140757", "av": False},
        ),
    ],
)
def test_filename_fields(filename, expect):
    meta = parse_filename(filename)
    assert meta.raw == filename
    assert meta.application_token == expect["application_token"]
    assert meta.timestamp_token == expect["timestamp_token"]
    assert meta.advanced_verification_marker is expect["av"]


def test_catalog_token_extracted():
    meta = parse_filename("MA5-12557-P53-WB-1-20241029_101909.jpg")
    assert meta.catalog_token == "MA5-12557"


def test_third_party_legacy_filename_extracts_pubmed_id():
    meta = parse_filename("MA512557-28843151-p53-gr3(20468).jpg")
    assert meta.pubmed_id == "28843151"


def test_tfs_prefixed_filename_is_left_for_provenance_to_handle():
    # tfs_ images are third-party via BenchSci; the filename has no trustworthy
    # catalog/application, so we don't invent one.
    meta = parse_filename("tfs_25237_biology-11-01719-g007.jpg")
    assert meta.application_token is None
    assert meta.catalog_token is None


def test_shared_timestamp_is_captured_verbatim():
    a = parse_filename("MA512557-Cellulartumorantigenp53-AV1-WB-20200824211338.jpg")
    b = parse_filename("MA512557-Cellulartumorantigenp53-ICC-20200824211338.jpg")
    # Same verbatim timestamp across two images — the bookkeeping tell phase 2 queries on.
    assert a.timestamp_token == b.timestamp_token == "20200824211338"
