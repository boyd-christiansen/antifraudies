from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def media_items_value() -> str:
    """The real ``media-items`` attribute value captured from the MA5-12557 page."""
    return (FIXTURES / "MA5-12557.media-items.txt").read_text(encoding="utf-8")
