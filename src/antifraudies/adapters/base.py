"""The vendor adapter contract.

Every vendor is a thin adapter over the same underlying shape — a product catalog with an
enumeration problem, verification images partitioned by provenance, and per-image
metadata — emitting one normalized record schema. The orchestrator and store never know
which vendor they are handling.

The interface deliberately separates *enumeration* (getting the list of products to
visit, a real subproblem at catalog scale) from *fetching one product*, and it abstracts
*how* a page's data is obtained so a future headless-browser / JSON-API implementation
can replace the current embedded-HTML parse without touching the store or pipelines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator

from ..models import ProductRef, ScrapeResult

__all__ = ["VendorAdapter", "ProductRef"]


class VendorAdapter(ABC):
    #: Stable vendor slug, used as a key everywhere (DB, registry, paths).
    vendor: str

    @abstractmethod
    def enumerate(self, limit: int | None = None) -> Iterator[ProductRef]:
        """Yield products to visit, from the vendor's sitemap/listing (robots-allowed)."""

    @abstractmethod
    def seed(self, entries: Iterable[str]) -> Iterator[ProductRef]:
        """Yield ProductRefs for an explicit bounded seed list (URLs or catalog numbers)."""

    @abstractmethod
    def fetch_product(self, ref: ProductRef) -> ScrapeResult:
        """Fetch and parse one product page into the normalized schema.

        Implementations must record the raw page bytes for evidence and must classify
        every image's provenance. They must not assert manipulation.
        """
