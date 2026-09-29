from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from trilhadocs.cli import app
from trilhadocs.config import load_config
from trilhadocs.inventory import load_inventory
from trilhadocs.paths import resolve_source
from trilhadocs.pdf_validation import validate_pdf

runner = CliRunner()


def json_output(result: object) -> dict[str, object]:
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_synthetic_demo_runs_validate_preview_build_and_verify(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[2]
    demo_template = project_root / "examples" / "demo"
    demo_root = tmp_path / "d"
    config_template = (demo_template / "config.toml").read_bytes()
    inventory_template = (demo_template / "inventory.jsonl").read_bytes()
    source_files_in_repo_before = list((demo_template / "sources").glob("**/*"))

    environment = os.environ.copy()
    source_root = str(project_root / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (source_root, environment.get("PYTHONPATH")))
    )
    generated = subprocess.run(
        [sys.executable, str(demo_template / "create_demo.py"), str(demo_root)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert generated.returncode == 0, generated.stderr
    assert (demo_root / "config.toml").read_bytes() == config_template
    assert (demo_root / "inventory.jsonl").read_bytes() == inventory_template
    assert not (demo_template / "sources").exists()
    assert source_files_in_repo_before == []

    config = load_config(demo_root / "config.toml")
    inventory = load_inventory(config.inventory_path)
    accounts = tuple(inventory.accounts.values())
    assert {account.status for account in accounts} == {"completed", "pending"}
    completed = next(account for account in accounts if account.status == "completed")
    pending = next(account for account in accounts if account.status == "pending")
    assert completed.cover is not None
    assert pending.cover is None
    assert len(inventory.attachments) == 2

    file_references = [account.cover for account in accounts if account.cover is not None]
    file_references.extend(inventory.attachments)
    referenced_files = [
        resolve_source(config.source_root, record.source_path) for record in file_references
    ]
    assert all(validate_pdf(path) == 1 for path in referenced_files)
    source_snapshot = {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in referenced_files
    }

    validated = runner.invoke(app, ["validate", "--config", str(demo_root / "config.toml")])
    previewed = runner.invoke(app, ["preview", "--config", str(demo_root / "config.toml")])

    assert validated.exit_code == 0
    assert json_output(validated)["status"] == "VALID"
    assert previewed.exit_code == 0
    assert json_output(previewed)["status"] == "READY"
    assert json_output(previewed)["member_count"] == 3
    assert not config.output_dir.exists()

    built = runner.invoke(app, ["build", "--config", str(demo_root / "config.toml")])
    verified = runner.invoke(app, ["verify", "--config", str(demo_root / "config.toml")])

    assert built.exit_code == 0
    assert json_output(built)["status"] == "COMPLETE"
    assert json_output(built)["archive_count"] == 1
    assert json_output(built)["member_count"] == 3
    assert verified.exit_code == 0
    assert json_output(verified)["valid"] is True
    assert json_output(verified)["member_count"] == 3
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in referenced_files
    } == source_snapshot


def test_demo_rejects_source_symlink_into_checkout_before_writing(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[2]
    demo_template = project_root / "examples" / "demo"
    demo_root = tmp_path / "outside-demo"
    demo_root.mkdir()
    checkout_target = project_root / f".demo-symlink-target-{tmp_path.name}"
    assert not checkout_target.exists()
    checkout_target.mkdir()
    source_link = demo_root / "sources"

    try:
        source_link.symlink_to(checkout_target, target_is_directory=True)
    except OSError as error:
        checkout_target.rmdir()
        if os.name == "nt" and getattr(error, "winerror", None) in {5, 1314}:
            pytest.skip(f"Windows negou a criação do symlink de teste: {error}")
        raise

    def snapshot_checkout_target() -> dict[str, tuple[int, str]]:
        return {
            str(path.relative_to(checkout_target)): (
                path.stat().st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in checkout_target.rglob("*")
            if path.is_file()
        }

    try:
        files_before = snapshot_checkout_target()
        environment = os.environ.copy()
        source_root = str(project_root / "src")
        environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, (source_root, environment.get("PYTHONPATH")))
        )
        generated = subprocess.run(
            [sys.executable, str(demo_template / "create_demo.py"), str(demo_root)],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        assert snapshot_checkout_target() == files_before, (
            "a demo gravou ou alterou arquivos dentro do checkout"
        )
        assert generated.returncode != 0, generated.stderr
        assert {path.name for path in demo_root.iterdir()} == {"sources"}
    finally:
        shutil.rmtree(checkout_target)
