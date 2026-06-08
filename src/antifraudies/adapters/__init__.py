"""Per-vendor adapters. Each emits the one normalized schema in ``antifraudies.models``.

Thermo Fisher is the first adapter, not a special case hard-coded elsewhere. Adding a
vendor means adding an adapter here; nothing downstream changes.
"""

from .base import ProductRef, VendorAdapter
from .thermofisher.adapter import ThermoFisherAdapter

# Registry keyed by vendor slug, so the CLI/orchestrator stays vendor-agnostic.
ADAPTERS: dict[str, type[VendorAdapter]] = {
    ThermoFisherAdapter.vendor: ThermoFisherAdapter,
}

__all__ = ["VendorAdapter", "ProductRef", "ThermoFisherAdapter", "ADAPTERS"]
