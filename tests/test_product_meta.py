"""Product-metadata parsing, incl. the clone-from-name fix (clone must not pick up a
competitor clone named in a caption)."""

import pytest

from antifraudies.adapters.thermofisher.parse import parse_product_metadata

URL = "https://www.thermofisher.com/antibody/product/x/MA5-12557"


@pytest.mark.parametrize(
    "name,expected_clone,expected_target",
    [
        ("p53 Monoclonal Antibody (DO-7)", "DO-7", "p53"),
        ("ESD Monoclonal Antibody (2F5E1)", "2F5E1", "ESD"),
        ("CSN7b Polyclonal Antibody", None, "CSN7b"),  # polyclonal -> no clone
    ],
)
def test_clone_and_target_from_name(name, expected_clone, expected_target):
    html = f"var productName ='{name}';"
    product = parse_product_metadata(html, catalog_number="MA5-12557", product_url=URL)
    assert product.product_name == name
    assert product.clone == expected_clone
    assert product.target == expected_target


def test_clone_ignores_competitor_clone_in_caption():
    # A caption naming a competitor's clone ("1C12") must NOT become this product's clone.
    html = (
        "var productName ='p53 Monoclonal Antibody (DO-7)';"
        "...top-cited monoclonal antibody (clone 1C12) from Supplier 1..."
    )
    product = parse_product_metadata(html, catalog_number="MA5-12557", product_url=URL)
    assert product.clone == "DO-7"
