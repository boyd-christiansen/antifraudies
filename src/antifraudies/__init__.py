"""antifraudies — catalog-scale forensic image-provenance pipeline for antibody vendor
verification images.

Phase 1 (implemented): scrape verification images + metadata, record provenance, and
persist everything as preserved evidence in a normalized, cross-image-queryable store.
Phase 2 (architected, not built): a cost-ordered forensic funnel that consumes this store
and produces a ranked, evidence-backed human review queue.

This system surfaces *apparent* manipulation for human review. It never renders a verdict.
"""

__version__ = "0.1.0"
