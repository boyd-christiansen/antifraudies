"""Rendered-modality taxonomy and classifier.

A verification image's *assay* (the ``application`` field: WB, IHC, Flow, ...) is not the
same as how the image is *rendered*, and only the rendering determines which forensics
apply. A "WB" entry might be a photographic blot membrane OR a bar chart quantifying that
blot; "ChIP" might be a gel or a microplate bar graph. Band extraction (e.g. SAM) only
makes sense on actual blot/gel images; running it on a flow-cytometry histogram or a
relative-expression bar chart is meaningless.

So we classify the rendered modality on a separate axis from assay and provenance:

  - BLOT_GEL        grayscale photographic bands on a membrane/gel  -> the primary forensic
                    target (band segmentation + matching, background reuse, copy-move).
  - MICROSCOPY      ICC/IF, IHC tissue/cell fields                  -> copy-move / splice / reuse.
  - PLOT_CHART      flow histograms, bar/line graphs, qPCR          -> data-rendered; pixel-band
                    forensics do NOT apply (only whole-image reuse).
  - COMPOSITE_PANEL multi-panel montage (esp. third-party figures)  -> split, then route panels.
  - UNKNOWN         no confident signal yet.

This is the cheap *metadata-prior* tier: it uses the ``appAbv`` label plus caption keywords
we already have, so it can tag the whole catalog for free. A later image-feature pass (and a
VLM on the ambiguous tail) confirms or corrects it; ``confidence`` marks which images need
that second look. The classifier returns its basis rather than silently resolving conflicts,
mirroring the provenance classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Modality(StrEnum):
    BLOT_GEL = "blot_gel"
    MICROSCOPY = "microscopy"
    PLOT_CHART = "plot_chart"
    COMPOSITE_PANEL = "composite_panel"
    UNKNOWN = "unknown"

    @property
    def supports_band_extraction(self) -> bool:
        """Only blot/gel images have extractable bands (the SAM / band-matching stream)."""
        return self is Modality.BLOT_GEL

    @property
    def runs_pixel_forensics(self) -> bool:
        """Charts are rendered from data — pixel-level forensics don't apply to them."""
        return self in {Modality.BLOT_GEL, Modality.MICROSCOPY, Modality.COMPOSITE_PANEL}


# appAbv (normalized: uppercased, non-alphanumerics stripped) -> modality prior.
# None means "ambiguous from the label alone — defer to the caption".
_APP_PRIOR: dict[str, Modality | None] = {
    "WB": Modality.BLOT_GEL,
    "TM": Modality.BLOT_GEL,      # cell treatment — shown as a western blot
    "KD": Modality.BLOT_GEL,      # knockdown — shown as a western blot
    "KO": Modality.BLOT_GEL,      # knockout — shown as a western blot
    "CRISPR": Modality.BLOT_GEL,
    "BM": Modality.BLOT_GEL,      # benchmarking — western blot comparison
    "ICCIF": Modality.MICROSCOPY,
    "ICC": Modality.MICROSCOPY,
    "IF": Modality.MICROSCOPY,
    "IHC": Modality.MICROSCOPY,
    "RE": Modality.PLOT_CHART,    # relative expression — bar chart
    "FLOW": Modality.PLOT_CHART,
    "FC": Modality.PLOT_CHART,
    "CHIP": None,                 # gel vs microplate bar graph — caption decides
}

_KEYWORDS: dict[Modality, tuple[str, ...]] = {
    Modality.BLOT_GEL: ("western blot", "immunoblot", "blotting", " blot ", "wb analysis"),
    Modality.MICROSCOPY: (
        "immunofluorescence", "immunocytochem", "immunohistochem", "confocal",
        "microscop", "counterstain", "paraffin", "dapi", "stained", "staining of",
    ),
    Modality.PLOT_CHART: (
        "relative expression", "bar graph", "flow cytometry", "histogram",
        "fold enrichment", "microplate", "qpcr", "rt-pcr", "quantif",
        "mean fluorescence", "scatter plot",
    ),
}


@dataclass(frozen=True)
class ModalityResult:
    modality: Modality
    confidence: str  # "high" | "medium" | "low"
    basis: str


def _norm_app(app: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (app or "").upper())


def _caption_modality(text: str) -> tuple[Modality | None, bool]:
    """Return (single modality hinted by keywords, whether multiple were hinted)."""
    hits = {m for m, kws in _KEYWORDS.items() if any(k in text for k in kws)}
    if len(hits) == 1:
        return next(iter(hits)), False
    return None, len(hits) > 1


def classify_modality(
    *,
    application_abbrev: str | None,
    application_name: str | None = None,
    caption: str | None = None,
) -> ModalityResult:
    app = _norm_app(application_abbrev)
    prior = _APP_PRIOR.get(app)  # may be a Modality, or None (ambiguous / unmapped)

    # Scan the caption ONLY for keywords. application_name just restates the assay label, so
    # folding it in would double-count the label's prior and mask real caption disagreements.
    cap_modality, multi = _caption_modality((caption or "").lower())

    if prior and cap_modality:
        if prior == cap_modality:
            return ModalityResult(prior, "high", f"appAbv {app} + caption agree")
        # Disagreement: keep the label's prior, but mark low confidence so the image-feature
        # / VLM tier takes a second look. These are exactly the cases worth confirming.
        return ModalityResult(
            prior, "low", f"appAbv {app}->{prior.value}; caption suggests {cap_modality.value}"
        )
    if prior:
        return ModalityResult(prior, "medium", f"appAbv {app}")
    if cap_modality:
        return ModalityResult(cap_modality, "medium", "caption keywords")
    if multi:
        return ModalityResult(
            Modality.UNKNOWN, "low", "multiple modality keywords (possible composite panel)"
        )
    return ModalityResult(Modality.UNKNOWN, "low", f"no modality signal (appAbv {app or '∅'})")
