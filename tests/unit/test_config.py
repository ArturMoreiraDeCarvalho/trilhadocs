from pathlib import Path

import pytest

from trilhadocs.config import ConfigurationError, load_config


def write_config(root: Path, body: str) -> Path:
    config_path = root / "nested" / "project.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(body, encoding="utf-8")
    return config_path


def valid_config() -> str:
    return """
schema_version = 1

[paths]
inventory = "inventory.jsonl"
source_root = "sources"
output_dir = "output"

[build]
path_limit = 185
max_workers = 4
create_master = true
"""


def test_load_config_resolves_paths_relative_to_config(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, valid_config())

    config = load_config(config_path)

    assert config.inventory_path == (config_path.parent / "inventory.jsonl").resolve()
    assert config.source_root == (config_path.parent / "sources").resolve()
    assert config.output_dir == (config_path.parent / "output").resolve()
    assert config.path_limit == 185
    assert config.max_workers == 4
    assert config.create_master is True


def test_load_config_does_not_change_process_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = write_config(tmp_path, valid_config())
    working_directory = tmp_path / "caller"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    load_config(config_path)

    assert Path.cwd() == working_directory


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("schema_version = 1", "schema_version = 1\nunknown = true"),
        ('inventory = "inventory.jsonl"', 'inventory = "inventory.jsonl"\nunknown = "value"'),
        ("path_limit = 185", "path_limit = 186"),
        ("max_workers = 4", "max_workers = 0"),
        ("schema_version = 1", "schema_version = 2"),
    ],
)
def test_load_config_rejects_unknown_or_invalid_values(
    tmp_path: Path, original: str, replacement: str
) -> None:
    body = valid_config().replace(original, replacement, 1)
    config_path = write_config(tmp_path, body)

    with pytest.raises(ConfigurationError):
        load_config(config_path)


def test_load_config_rejects_missing_required_sections(tmp_path: Path) -> None:
    config_path = write_config(tmp_path, "schema_version = 1\n")

    with pytest.raises(ConfigurationError):
        load_config(config_path)
