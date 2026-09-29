from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from threading import Barrier, Lock

import pytest
from test_build import fixture_job
from typer.testing import CliRunner

from trilhadocs import cli
from trilhadocs.cli import app
from trilhadocs.config import load_config
from trilhadocs.inventory import load_inventory
from trilhadocs.packaging import BuildResult
from trilhadocs.planning import build_member_plan

runner = CliRunner()


def write_cli_project(tmp_path: Path) -> tuple[Path, Path]:
    job = fixture_job(tmp_path)
    inventory_path = tmp_path / "inventory.jsonl"
    inventory_path.write_text(
        "".join(record.model_dump_json() + "\n" for record in job.inventory.records),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            (
                "schema_version = 1",
                "",
                "[paths]",
                'inventory = "inventory.jsonl"',
                'source_root = "sources"',
                f'output_dir = "../{job.config.output_dir.name}"',
                "",
                "[build]",
                "path_limit = 185",
                "max_workers = 2",
                "create_master = true",
                "",
            )
        ),
        encoding="utf-8",
    )
    return config_path, job.config.output_dir


def json_output(result: object) -> dict[str, object]:
    stdout = result.stdout
    return json.loads(stdout.strip().splitlines()[-1])


def write_invalid_pdf_with_bin_source(
    tmp_path: Path,
    *,
    output_filename: str = "Cover.pdf",
) -> None:
    inventory_path = tmp_path / "inventory.jsonl"
    records = [json.loads(line) for line in inventory_path.read_text("utf-8").splitlines()]
    account = next(record for record in records if record["record_type"] == "account")
    cover = account["cover"]
    invalid_pdf = b"synthetic bytes that are not a PDF"
    cover["source_path"] = "covers/account-1.bin"
    cover["filename"] = output_filename
    cover["size_bytes"] = len(invalid_pdf)
    cover["sha256"] = hashlib.sha256(invalid_pdf).hexdigest()
    source_path = tmp_path / "sources" / cover["source_path"]
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(invalid_pdf)
    serialized_records = "".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records
    )
    inventory_path.write_text(
        serialized_records,
        encoding="utf-8",
    )


def test_validate_and_preview_do_not_write_output_or_expose_names(tmp_path: Path) -> None:
    config_path, output_dir = write_cli_project(tmp_path)

    validated = runner.invoke(app, ["validate", "--config", str(config_path)])
    previewed = runner.invoke(app, ["preview", "--config", str(config_path)])

    assert validated.exit_code == 0
    assert previewed.exit_code == 0
    assert json_output(validated)["status"] == "VALID"
    assert json_output(previewed)["archive_count"] == 2
    assert not output_dir.exists()
    for result in (validated, previewed):
        assert str(config_path) not in result.stdout
        assert str(output_dir) not in result.stdout
        assert "Synthetic Company A" not in result.stdout
        assert "account-1" not in result.stdout


def test_validate_inspects_sources_in_configured_bounded_parallelism(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _ = write_cli_project(tmp_path)
    config = load_config(config_path)
    inventory = load_inventory(config.inventory_path)
    plan = build_member_plan(config, inventory)
    both_workers_started = Barrier(2, timeout=2)
    active = 0
    maximum_active = 0
    inspected = 0
    lock = Lock()

    def inspect_in_parallel(*_args: object) -> None:
        nonlocal active, maximum_active, inspected
        with lock:
            active += 1
            inspected += 1
            maximum_active = max(maximum_active, active)
        try:
            both_workers_started.wait()
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(cli, "inspect_file", inspect_in_parallel)
    monkeypatch.setattr(cli, "validate_pdf", lambda _path: 1)

    cli._validate_sources(config, inventory, plan)

    assert inspected == 4
    assert maximum_active == config.max_workers == 2


def test_build_then_verify_return_zero_with_redacted_json(tmp_path: Path) -> None:
    config_path, output_dir = write_cli_project(tmp_path)

    built = runner.invoke(app, ["build", "--config", str(config_path)])
    verified = runner.invoke(app, ["verify", "--config", str(config_path)])

    assert built.exit_code == 0
    assert verified.exit_code == 0
    assert json_output(built)["status"] == "COMPLETE"
    assert json_output(verified)["valid"] is True
    assert str(output_dir) not in built.stdout
    assert "Synthetic Company A" not in built.stdout
    assert "account-1" not in verified.stdout


def test_build_resume_rejects_symlinked_journal_without_modifying_external_file(
    tmp_path: Path,
) -> None:
    config_path, output_dir = write_cli_project(tmp_path)
    built = runner.invoke(app, ["build", "--config", str(config_path)])
    assert built.exit_code == 0

    journal_path = output_dir / ".trilhadocs-journal.jsonl"
    journal_lines = journal_path.read_text("utf-8").splitlines()
    external_journal = tmp_path / "external-journal.jsonl"
    external_journal.write_text("\n".join(journal_lines[:-1]) + "\n", encoding="utf-8")
    journal_path.unlink()
    try:
        journal_path.symlink_to(external_journal)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"File symlinks are unavailable here: {error}")
    external_before_resume = external_journal.read_bytes()

    resumed = runner.invoke(
        app,
        ["build", "--config", str(config_path), "--resume"],
    )

    assert resumed.exit_code == 3
    assert json_output(resumed)["status"] == "BUILD_FAILURE"
    assert journal_path.is_symlink()
    assert external_journal.read_bytes() == external_before_resume


def test_validate_rejects_invalid_pdf_named_member_with_bin_source(tmp_path: Path) -> None:
    config_path, output_dir = write_cli_project(tmp_path)
    write_invalid_pdf_with_bin_source(tmp_path)

    result = runner.invoke(app, ["validate", "--config", str(config_path)])

    assert result.exit_code == 3
    assert json_output(result)["status"] == "INTEGRITY_FAILURE"
    assert not output_dir.exists()


def test_validate_uses_sanitized_pdf_suffix_for_item_with_trailing_period(
    tmp_path: Path,
) -> None:
    config_path, output_dir = write_cli_project(tmp_path)
    write_invalid_pdf_with_bin_source(tmp_path, output_filename="item.pdf.")

    result = runner.invoke(app, ["validate", "--config", str(config_path)])

    assert result.exit_code == 3
    assert json_output(result)["status"] == "INTEGRITY_FAILURE"
    assert not output_dir.exists()


def test_build_rejects_invalid_pdf_named_member_with_bin_source(tmp_path: Path) -> None:
    config_path, output_dir = write_cli_project(tmp_path)
    write_invalid_pdf_with_bin_source(tmp_path)

    result = runner.invoke(app, ["build", "--config", str(config_path)])

    assert result.exit_code == 3
    assert json_output(result)["status"] == "BUILD_FAILURE"
    assert not (output_dir / "trilhadocs-pacotes.zip").exists()


def test_invalid_config_returns_exit_two_without_output(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.toml"
    config_path.write_text("[paths\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", "--config", str(config_path)])

    assert result.exit_code == 2
    assert not (tmp_path / "out").exists()


def test_duplicate_inventory_id_returns_redacted_exit_two(tmp_path: Path) -> None:
    config_path, _ = write_cli_project(tmp_path)
    inventory_path = tmp_path / "inventory.jsonl"
    lines = inventory_path.read_text(encoding="utf-8").splitlines()
    inventory_path.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")

    result = runner.invoke(app, ["validate", "--config", str(config_path)])

    assert result.exit_code == 2
    assert "account-1" not in result.stdout
    assert str(config_path) not in result.stdout


def test_partial_build_returns_exit_three(tmp_path: Path, monkeypatch) -> None:
    config_path, _ = write_cli_project(tmp_path)
    monkeypatch.setattr(
        "trilhadocs.cli.build_job",
        lambda *_args, **_kwargs: BuildResult(
            complete=False,
            archive_count=0,
            member_count=0,
            output_bytes=0,
            plan_sha256="a" * 64,
        ),
    )

    result = runner.invoke(app, ["build", "--config", str(config_path)])

    assert result.exit_code == 3
    assert json_output(result)["status"] == "PARTIAL"


def test_importing_all_modules_is_quiet_and_has_no_external_side_effects(
    tmp_path: Path,
) -> None:
    script = """
import importlib
import os
import pkgutil
import socket
import subprocess

def blocked(*_args, **_kwargs):
    raise AssertionError("external side effect during import")

socket.create_connection = blocked
socket.socket.connect = blocked
os.system = blocked
for name in ("Popen", "run", "call", "check_call", "check_output"):
    setattr(subprocess, name, blocked)

import trilhadocs
for module in pkgutil.iter_modules(trilhadocs.__path__):
    importlib.import_module(f"trilhadocs.{module.name}")
"""
    environment = os.environ.copy()
    project_source = str(Path(__file__).parents[2] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (project_source, environment.get("PYTHONPATH")))
    )
    environment["PYTHONDONTWRITEBYTECODE"] = "1"

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []


def test_build_conflict_and_tampered_verify_return_exit_three(tmp_path: Path) -> None:
    config_path, output_dir = write_cli_project(tmp_path)
    built = runner.invoke(app, ["build", "--config", str(config_path)])
    conflict = runner.invoke(app, ["build", "--config", str(config_path)])
    master_path = output_dir / "trilhadocs-pacotes.zip"
    master_path.write_bytes(master_path.read_bytes() + b"tampered")
    tampered = runner.invoke(app, ["verify", "--config", str(config_path)])

    assert built.exit_code == 0
    assert conflict.exit_code == 3
    assert tampered.exit_code == 3
    assert str(output_dir) not in conflict.stdout
    assert "Synthetic Company A" not in tampered.stdout
