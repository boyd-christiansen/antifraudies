"""Phase-2 forensic detectors.

A cost-ordered funnel over the shared store: cheap detectors run on everything, expensive
ones run only on survivors. Each detector reads the store and writes rows into `findings`,
which surfaces *apparent* anomalies (with evidence) for human review — never a verdict.

The conceptual design lives in `pipelines/README.md`; the runnable code lives here in the
package so it can import the store/models and be tested. Detectors are idempotent: a finding
is identified by `(finding_type, finding_key)`, so re-running updates rather than duplicates.
"""

from .findings import FindingGroup, provenance_pair, severity_for, write_findings

__all__ = ["FindingGroup", "write_findings", "severity_for", "provenance_pair"]
