"""Provenance taxonomy and classification.

The single most important distinction in this project is *who produced an image*:

  - the vendor's OWN internal verification data  (the forensic target), versus
  - third-party content pulled from published papers (a separate corpus).

These must never be conflated: "the vendor fabricated this" and "the vendor reused a
published figure" are entirely different claims. Every image records its provenance.

For Thermo Fisher the signal is reliable and comes from three corroborating sources,
in priority order:

  1. ``sourceType`` integer on each image record  (primary)
       1 = "Antibody Testing Data"      -> internal
       2 = "Advanced Verification"      -> internal
       3 = "Published Figures"          -> third party (served via BenchSci)
  2. the data-island group key the record was listed under
  3. filename / field markers: ``benchSciPubmedId`` != "0" and a ``tfs_`` filename
     prefix both indicate a third-party published figure.

The classifier prefers the primary signal and uses the others to corroborate; a
disagreement is surfaced (returned) so it can be logged rather than silently resolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Provenance(StrEnum):
    """Normalized, vendor-agnostic provenance categories."""

    INTERNAL_TESTING_DATA = "internal_testing_data"
    INTERNAL_ADVANCED_VERIFICATION = "internal_advanced_verification"
    THIRD_PARTY_PUBLISHED_FIGURE = "third_party_published_figure"
    UNKNOWN = "unknown"

    @property
    def is_internal(self) -> bool:
        """True for the vendor's own data — the forensic target of phase 2."""
        return self in {
            Provenance.INTERNAL_TESTING_DATA,
            Provenance.INTERNAL_ADVANCED_VERIFICATION,
        }

    @property
    def is_third_party(self) -> bool:
        return self is Provenance.THIRD_PARTY_PUBLISHED_FIGURE


# Thermo Fisher sourceType code -> normalized provenance.
_SOURCE_TYPE_MAP = {
    "1": Provenance.INTERNAL_TESTING_DATA,
    "2": Provenance.INTERNAL_ADVANCED_VERIFICATION,
    "3": Provenance.THIRD_PARTY_PUBLISHED_FIGURE,
}

# Human-readable group key -> normalized provenance (corroborating signal).
_GROUP_KEY_MAP = {
    "antibody testing data": Provenance.INTERNAL_TESTING_DATA,
    "advanced verification": Provenance.INTERNAL_ADVANCED_VERIFICATION,
    "published figures": Provenance.THIRD_PARTY_PUBLISHED_FIGURE,
    "published figure": Provenance.THIRD_PARTY_PUBLISHED_FIGURE,
}


@dataclass(frozen=True)
class ProvenanceResult:
    provenance: Provenance
    disagreement: str | None = None  # non-None when signals conflict (worth logging)


def classify_thermofisher(
    *,
    source_type: str | None,
    group_key: str | None = None,
    benchsci_pubmed_id: str | None = None,
    image_filename: str | None = None,
) -> ProvenanceResult:
    """Classify a Thermo Fisher image record's provenance.

    ``source_type`` is the primary signal. ``group_key`` (the data-island category the
    record was nested under) and the BenchSci/filename markers corroborate it.
    """
    primary = _SOURCE_TYPE_MAP.get((source_type or "").strip())

    # Corroborating signals.
    corroborating: Provenance | None = None
    if group_key is not None:
        corroborating = _GROUP_KEY_MAP.get(group_key.strip().lower())

    third_party_markers = []
    if benchsci_pubmed_id and benchsci_pubmed_id.strip() not in {"", "0"}:
        third_party_markers.append(f"benchSciPubmedId={benchsci_pubmed_id}")
    if image_filename and image_filename.lower().startswith("tfs_"):
        third_party_markers.append("filename tfs_ prefix")

    # Resolve.
    resolved = primary or corroborating
    if resolved is None and third_party_markers:
        resolved = Provenance.THIRD_PARTY_PUBLISHED_FIGURE
    if resolved is None:
        return ProvenanceResult(
            Provenance.UNKNOWN,
            disagreement=f"no source_type/group_key (markers={third_party_markers or 'none'})",
        )

    # Flag conflicts between signals without overriding the primary one.
    notes = []
    if primary and corroborating and primary != corroborating:
        notes.append(f"sourceType={primary.value} vs group_key={corroborating.value}")
    if third_party_markers and resolved.is_internal:
        notes.append(
            f"resolved internal but third-party markers present ({', '.join(third_party_markers)})"
        )
    return ProvenanceResult(resolved, disagreement="; ".join(notes) or None)
