from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ConfigurationError(ValueError):
    """Safe, user-facing error raised for invalid or unreadable configuration."""


class _StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _PathsConfig(_StrictConfigModel):
    inventory: str = Field(min_length=1)
    source_root: str = Field(min_length=1)
    output_dir: str = Field(min_length=1)


class _BuildConfig(_StrictConfigModel):
    path_limit: int = Field(default=185, ge=1, le=185, strict=True)
    max_workers: int = Field(default=4, ge=1, le=16, strict=True)
    create_master: bool = True


class _RawConfig(_StrictConfigModel):
    schema_version: Literal[1]
    paths: _PathsConfig
    build: _BuildConfig


class ProjectConfig(_StrictConfigModel):
    inventory_path: Path
    source_root: Path
    output_dir: Path
    path_limit: int = Field(ge=1, le=185)
    max_workers: int = Field(ge=1, le=16)
    create_master: bool


def _resolve_path(base_dir: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve(strict=False)


def load_config(path: Path) -> ProjectConfig:
    """Load strict TOML settings and resolve relative paths from the config file."""
    try:
        config_path = Path(path).expanduser().resolve(strict=True)
        raw_data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        raw = _RawConfig.model_validate(raw_data)
        base_dir = config_path.parent
        return ProjectConfig(
            inventory_path=_resolve_path(base_dir, raw.paths.inventory),
            source_root=_resolve_path(base_dir, raw.paths.source_root),
            output_dir=_resolve_path(base_dir, raw.paths.output_dir),
            path_limit=raw.build.path_limit,
            max_workers=raw.build.max_workers,
            create_master=raw.build.create_master,
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, ValidationError, ValueError):
        raise ConfigurationError("Configuração TOML inválida ou inacessível.") from None
