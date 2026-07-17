"""Tests for antifraudies.config — loading, env overrides, and coercion."""

from __future__ import annotations

from antifraudies.config import REPO_ROOT, _coerce, load_settings

# ── Default config loading ──────────────────────────────────────────────────


def test_load_default_config():
    """load_settings() with the shipped default.toml produces a valid Settings."""
    settings = load_settings()
    assert settings.crawl.user_agent  # non-empty
    assert settings.crawl.concurrency > 0
    assert settings.database.dsn.startswith("postgresql")
    assert settings.zenodo.doi


# ── Environment overrides ──────────────────────────────────────────────────


def test_env_override_simple(monkeypatch):
    """ANTIFRAUDIES_CRAWL__CONCURRENCY overrides crawl.concurrency."""
    monkeypatch.setenv("ANTIFRAUDIES_CRAWL__CONCURRENCY", "8")
    settings = load_settings()
    assert settings.crawl.concurrency == 8


def test_env_override_data_dir_shorthand(monkeypatch, tmp_path):
    """ANTIFRAUDIES_DATA_DIR is a top-level shorthand for paths.data_dir."""
    target = tmp_path / "custom_data"
    monkeypatch.setenv("ANTIFRAUDIES_DATA_DIR", str(target))
    settings = load_settings()
    assert settings.data_dir == target.resolve()


# ── _coerce ─────────────────────────────────────────────────────────────────


def test_coerce_bool_true():
    assert _coerce("true") is True


def test_coerce_bool_false():
    assert _coerce("false") is False


def test_coerce_int():
    assert _coerce("42") == 42
    assert isinstance(_coerce("42"), int)


def test_coerce_float():
    assert _coerce("3.14") == 3.14
    assert isinstance(_coerce("3.14"), float)


def test_coerce_string():
    assert _coerce("hello") == "hello"


# ── data_dir path resolution ───────────────────────────────────────────────


def test_data_dir_absolute_path(monkeypatch, tmp_path):
    """An absolute paths.data_dir is used as-is (e.g. external SSD mount)."""
    abs_dir = tmp_path / "absolute_storage"
    monkeypatch.setenv("ANTIFRAUDIES_DATA_DIR", str(abs_dir))
    settings = load_settings()
    assert settings.data_dir == abs_dir.resolve()


def test_data_dir_relative_path():
    """The default relative data_dir resolves under REPO_ROOT."""
    settings = load_settings()
    # default.toml has data_dir = "data" → should become <repo_root>/data
    assert settings.data_dir == (REPO_ROOT / "data").resolve()
