"""Unit tests for detector logic that doesn't need a database."""

import numpy as np
from PIL import Image

from antifraudies.detect.features import _grayscale_and_contrast
from antifraudies.detect.findings import params_hash, provenance_pair, severity_for
from antifraudies.detect.tier1 import cluster_near_duplicates

# ----------------------------------------------------------------- findings helpers

def test_provenance_pair_collapses_to_internal_third_party():
    assert provenance_pair(["internal_testing_data", "internal_advanced_verification"]) == (
        "internal"
    )
    assert provenance_pair(["third_party_published_figure"]) == "third_party"
    assert (
        provenance_pair(["internal_testing_data", "third_party_published_figure"])
        == "internal-third_party"
    )


def test_severity_thresholds():
    assert severity_for(2) == "low"
    assert severity_for(4) == "medium"
    assert severity_for(10) == "high"


def test_params_hash_is_deterministic_and_order_independent():
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})
    assert params_hash({"a": 1}) != params_hash({"a": 2})


# ----------------------------------------------------------------- near-dup clustering

def _item(i, catalog, bits, sha="s", prov="internal_testing_data"):
    return {"id": i, "catalog": catalog, "prov": prov, "sha": sha, "bits": bits}


def test_cluster_groups_near_hashes_across_products():
    items = [
        _item(1, "A", 0b0000, sha="a"),
        _item(2, "B", 0b0001, sha="b"),  # hamming 1 from #1, different product
        _item(3, "C", 0b1111_1111, sha="c"),  # far away, alone
    ]
    clusters = cluster_near_duplicates(items, max_hamming=2)
    assert len(clusters) == 1
    assert {m["id"] for m in clusters[0]} == {1, 2}


def test_cluster_ignores_byte_identical_pairs():
    # Same sha = exact reuse, handled by Tier 0; must not become a near_duplicate.
    items = [_item(1, "A", 0b0, sha="same"), _item(2, "B", 0b0, sha="same")]
    assert cluster_near_duplicates(items, max_hamming=4) == []


def test_cluster_requires_more_than_one_product():
    # Two near images on the SAME product is not a cross-product near-dup finding.
    items = [_item(1, "A", 0b0, sha="a"), _item(2, "A", 0b1, sha="b")]
    assert cluster_near_duplicates(items, max_hamming=4) == []


# ----------------------------------------------------------------- image features

def test_grayscale_detection():
    gray = Image.fromarray(np.full((16, 16, 3), 128, dtype=np.uint8))
    is_gray, _ = _grayscale_and_contrast(gray)
    assert is_gray is True

    color = np.zeros((16, 16, 3), dtype=np.uint8)
    color[..., 0] = 200  # red channel only
    is_gray2, _ = _grayscale_and_contrast(Image.fromarray(color))
    assert is_gray2 is False


def test_contrast_residual_higher_for_textured_image():
    flat = Image.fromarray(np.full((32, 32, 3), 100, dtype=np.uint8))
    noise = Image.fromarray(np.random.default_rng(0).integers(0, 255, (32, 32, 3), dtype=np.uint8))
    _, flat_c = _grayscale_and_contrast(flat)
    _, noise_c = _grayscale_and_contrast(noise)
    assert flat_c == 0.0
    assert noise_c > flat_c
