"""Polite, defensible crawling: cached + rate-limited HTTP, robots enforcement, archival."""

from .http import CachedResponse, PoliteClient
from .robots import RobotsPolicy

__all__ = ["PoliteClient", "CachedResponse", "RobotsPolicy"]
