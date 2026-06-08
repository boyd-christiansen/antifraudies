from antifraudies.provenance import Provenance, classify_thermofisher


def test_source_type_1_is_internal_testing_data():
    r = classify_thermofisher(source_type="1", group_key="Antibody Testing Data")
    assert r.provenance is Provenance.INTERNAL_TESTING_DATA
    assert r.provenance.is_internal
    assert r.disagreement is None


def test_source_type_2_is_internal_advanced_verification():
    r = classify_thermofisher(source_type="2", group_key="Advanced Verification")
    assert r.provenance is Provenance.INTERNAL_ADVANCED_VERIFICATION
    assert r.provenance.is_internal


def test_source_type_3_is_third_party():
    r = classify_thermofisher(
        source_type="3",
        group_key="Published Figures",
        benchsci_pubmed_id="36552229",
        image_filename="tfs_25237_biology-11-01719-g007.jpg",
    )
    assert r.provenance is Provenance.THIRD_PARTY_PUBLISHED_FIGURE
    assert r.provenance.is_third_party
    assert not r.provenance.is_internal


def test_filename_marker_resolves_third_party_when_source_type_missing():
    r = classify_thermofisher(source_type=None, image_filename="tfs_12153_ppat.1009033.g003.jpg")
    assert r.provenance is Provenance.THIRD_PARTY_PUBLISHED_FIGURE


def test_disagreement_is_flagged_not_silently_resolved():
    # Primary says internal, but a third-party marker is present -> resolve to primary,
    # but surface the conflict for logging.
    r = classify_thermofisher(source_type="1", benchsci_pubmed_id="28843151")
    assert r.provenance is Provenance.INTERNAL_TESTING_DATA
    assert r.disagreement is not None


def test_unknown_when_no_signal():
    r = classify_thermofisher(source_type=None)
    assert r.provenance is Provenance.UNKNOWN
