"""Configuration loading.

Reads ``config/default.toml`` and applies environment-variable overrides of the form
``ANTIFRAUDIES_<SECTION>__<KEY>`` (``__`` separates nesting levels). Returns a validated,
immutable :class:`Settings` object that the rest of the package depends on.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

# Repo root = two levels up from this file (src/antifraudies/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "default.toml"
ENV_PREFIX = "ANTIFRAUDIES_"


class PathsConfig(BaseModel):
    data_dir: str = "data"
    blobs_subdir: str = "blobs"
    cache_subdir: str = "cache"


class DatabaseConfig(BaseModel):
    # libpq DSN. Default connects to a local Postgres as the current user.
    dsn: str = "postgresql:///antifraudies"


class CrawlConfig(BaseModel):
    user_agent: str
    contact: str
    concurrency: int = 24
    min_interval_seconds: float = 0.0
    max_retries: int = 4
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 60.0
    jitter_seconds: float = 0.5
    timeout_seconds: float = 30.0
    respect_robots: bool = True
    cache_enabled: bool = False


class ZenodoConfig(BaseModel):
    doi: str
    download_bytes: bool = False


class Settings(BaseModel):
    paths: PathsConfig
    database: DatabaseConfig = DatabaseConfig()
    crawl: CrawlConfig
    zenodo: ZenodoConfig

    # Absolute path to the repo root, resolved at load time. Not from TOML.
    repo_root: Path = REPO_ROOT

    @property
    def data_dir(self) -> Path:
        # Absolute paths (e.g. an external SSD) and ~ are honored; a relative path is taken
        # under the repo root. This is what ANTIFRAUDIES_DATA_DIR points at.
        p = Path(self.paths.data_dir).expanduser()
        return p.resolve() if p.is_absolute() else (self.repo_root / p).resolve()

    @property
    def blobs_dir(self) -> Path:
        return self.data_dir / self.paths.blobs_subdir

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / self.paths.cache_subdir

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.blobs_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)


def _coerce(value: str) -> object:
    """Best-effort coercion of an env-var string into bool/number/str."""
    low = value.lower()
    if low in {"true", "false"}:
        return low == "true"
    for caster in (int, float):
        try:
            return caster(value)
        except ValueError:
            pass
    return value


def _apply_env_overrides(data: dict) -> dict:
    for key, raw in os.environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        path = key[len(ENV_PREFIX) :].lower().split("__")
        cursor = data
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        if isinstance(cursor, dict):
            cursor[path[-1]] = _coerce(raw)
    return data


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or DEFAULT_CONFIG_PATH
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    data = _apply_env_overrides(data)
    # Convenience: ANTIFRAUDIES_DATA_DIR is a shorthand for paths.data_dir — the one knob most
    # people relocate (point the image-blob/cache storage at an external disk). Accepts an
    # absolute path. The generic override lands it as a top-level "data_dir"; route it to paths.
    if "data_dir" in data and not isinstance(data["data_dir"], dict):
        data.setdefault("paths", {})["data_dir"] = data.pop("data_dir")
    return Settings(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings for the default config path."""
    return load_settings()
