# Phase 2 — human review tooling (placeholder, NOT implemented)

> [!IMPORTANT]
> Not implemented in phase 1. Documented placeholder only.

The end product of the phase-2 funnel (`../pipelines/scoring/`) is a **ranked, evidence-
backed review queue** for a qualified human to adjudicate. This directory will hold that
tooling: a way to step through flagged cases, each presented with its supporting evidence —
the implicated images at full resolution, the cross-image matches that triggered the flag
(duplicate, reused background, matched band under transform), the relevant captions and
filename metadata, and links to the preserved raw bytes and page snapshots.

**Framing discipline (binding here especially):** the queue presents *apparent* anomalies
and the evidence for them. It assigns no verdict. Labels, copy, and exports must read as
"flagged for review" / "apparent" — never "confirmed manipulation." The human decides.

Consumes: the shared evidence store (`../src/antifraudies/store/`) plus phase-2 derived
artifacts under `../pipelines/`. Nothing here modifies raw captures.
