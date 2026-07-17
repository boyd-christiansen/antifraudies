"""Structured logging for antifraudies.

Replaces ad-hoc ``print(..., file=sys.stderr)`` calls with stdlib ``logging``,
giving users control over log levels, formatting, and output destinations.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(*, verbose: bool = False) -> None:
    """Configure the root ``antifraudies`` logger.

    - **INFO** (default): progress milestones, summaries, warnings.
    - **DEBUG** (``--verbose``): per-URL fetches, per-image feature computations, cache
      hits/misses.
    """
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-5s %(name)s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger("antifraudies")
    root.setLevel(level)
    # Avoid duplicate handlers when setup_logging is called more than once
    # (e.g. in tests or when multiple CLI commands are chained).
    if not root.handlers:
        root.addHandler(handler)
