from antifraudies.modality import Modality, classify_modality


def test_western_blot_label_and_caption_agree_high():
    r = classify_modality(
        application_abbrev="WB",
        application_name="Western Blot",
        caption="Western blot using p53 Monoclonal Antibody (DO-7) shows induction...",
    )
    assert r.modality is Modality.BLOT_GEL
    assert r.confidence == "high"
    assert r.modality.supports_band_extraction


def test_treatment_is_a_blot_not_a_chart():
    # "TM" (cell treatment) is a validation strategy; the image is a western blot.
    r = classify_modality(
        application_abbrev="TM",
        application_name="Cell treatment",
        caption="Altered expression upon treatment. Western blot using p53 Monoclonal...",
    )
    assert r.modality is Modality.BLOT_GEL


def test_relative_expression_is_a_chart():
    r = classify_modality(
        application_abbrev="RE",
        application_name="Relative expression",
        caption="Antibody specificity by detection of differential basal expression.",
    )
    assert r.modality is Modality.PLOT_CHART
    assert not r.modality.supports_band_extraction
    assert not r.modality.runs_pixel_forensics  # data-rendered, no pixel forensics


def test_flow_cytometry_is_a_chart():
    r = classify_modality(
        application_abbrev="Flow",
        application_name="Flow Cytometry",
        caption="Flow cytometry analysis of p53 was done on HeLa cells.",
    )
    assert r.modality is Modality.PLOT_CHART


def test_immunofluorescence_is_microscopy():
    r = classify_modality(
        application_abbrev="ICC/IF",
        application_name="Immunocytochemistry",
        caption="Immunofluorescence analysis of p53 was performed using MDA-MB-231 cells.",
    )
    assert r.modality is Modality.MICROSCOPY
    assert r.modality.runs_pixel_forensics
    assert not r.modality.supports_band_extraction


def test_ambiguous_chip_resolved_by_caption():
    # "ChIP" alone is ambiguous (gel vs microplate); the caption decides.
    r = classify_modality(
        application_abbrev="ChIP",
        application_name="ChIP Assay",
        caption="Multiplex microplate Matrix ChIP fold enrichment was measured.",
    )
    assert r.modality is Modality.PLOT_CHART
    assert r.confidence in {"medium", "high"}


def test_label_caption_disagreement_is_low_confidence():
    # Keep the label's prior but flag low confidence for the image-feature / VLM tier.
    r = classify_modality(
        application_abbrev="WB",
        application_name="Western Blot",
        caption="Immunofluorescence confocal microscopy of stained cells.",
    )
    assert r.modality is Modality.BLOT_GEL
    assert r.confidence == "low"


def test_no_signal_is_unknown():
    r = classify_modality(application_abbrev=None, caption=None)
    assert r.modality is Modality.UNKNOWN
