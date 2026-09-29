from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest
from test_build import fixture_job

from trilhadocs.inventory import Inventory
from trilhadocs.models import AccountRecord
from trilhadocs.packaging import build_job
from trilhadocs.verification import (
    ARCHIVE_MANIFEST_FILENAME,
    SUMMARY_FILENAME,
    _validate_zip_entries,
    _VerificationFailure,
    verify_job,
)


def test_verify_job_accepts_a_complete_build_and_reports_counts(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan)

    result = verify_job(job.config.output_dir, job.inventory)

    assert result.valid is True
    assert result.archive_count == 2
    assert result.member_count == 4
    assert result.issues == ()


def test_verify_job_detects_a_missing_pair_archive(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan)
    job.plan.archives[0].output_path.unlink()

    result = verify_job(job.config.output_dir, job.inventory)

    assert result.valid is False
    assert result.issues


def test_verify_job_detects_changed_expected_inventory_content(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan)
    records = list(job.inventory.records)
    account_index = next(
        index for index, record in enumerate(records) if isinstance(record, AccountRecord)
    )
    account = records[account_index]
    assert isinstance(account, AccountRecord) and account.cover is not None
    changed_cover = account.cover.model_copy(update={"sha256": "d" * 64})
    records[account_index] = account.model_copy(update={"cover": changed_cover})
    altered_inventory = Inventory(records=tuple(records), sha256=job.inventory.sha256)

    result = verify_job(job.config.output_dir, altered_inventory)

    assert result.valid is False
    assert result.issues


def test_verify_job_detects_tampered_master_zip(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan)
    master_path = job.config.output_dir / (job.plan.master_filename or "")
    master_path.write_bytes(master_path.read_bytes() + b"tampered")

    result = verify_job(job.config.output_dir, job.inventory)

    assert result.valid is False
    assert result.issues


def test_verify_job_detects_tampered_pair_zip(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan)
    pair_path = job.plan.archives[0].output_path
    pair_path.write_bytes(pair_path.read_bytes() + b"tampered")

    result = verify_job(job.config.output_dir, job.inventory)

    assert result.valid is False
    assert result.issues


def test_verify_job_rejects_zip_symbolic_link_entries(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan)
    pair_path = job.plan.archives[0].output_path
    with zipfile.ZipFile(pair_path) as source:
        entries = [(info, source.read(info.filename)) for info in source.infolist()]
    target_info = entries[0][0]
    target_info.create_system = 3
    target_info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(pair_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info, data in entries:
            target.writestr(info, data)

    result = verify_job(job.config.output_dir, job.inventory)

    assert result.valid is False
    assert any("entrada que" in issue for issue in result.issues)


def test_verify_job_rejects_output_zip_symlink(tmp_path: Path, monkeypatch) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan)
    pair_path = job.plan.archives[0].output_path
    original_is_symlink = Path.is_symlink

    def report_pair_as_symlink(path: Path) -> bool:
        return path == pair_path or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_pair_as_symlink)

    result = verify_job(job.config.output_dir, job.inventory)

    assert result.valid is False
    assert any("arquivo regular" in issue for issue in result.issues)


def test_zip_entry_names_that_collide_on_windows_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "colliding.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("100 - Cash/Capa/Cover.pdf", b"first")
        archive.writestr("100 - cash/Capa/Cover.pdf", b"second")

    with zipfile.ZipFile(path) as archive, pytest.raises(_VerificationFailure):
        _validate_zip_entries(archive)


@pytest.mark.parametrize("path_variant", ["dot-segment", "repeated-separator"])
def test_verify_job_rejects_noncanonical_member_paths(tmp_path: Path, path_variant: str) -> None:
    job = fixture_job(tmp_path, create_master=False)
    build_job(job.config, job.inventory, job.plan)
    pair_path = job.plan.archives[0].output_path
    with zipfile.ZipFile(pair_path) as source:
        entries = [(info, source.read(info.filename)) for info in source.infolist()]

    manifest_bytes = next(
        data for info, data in entries if info.filename == ARCHIVE_MANIFEST_FILENAME
    )
    manifest = json.loads(manifest_bytes)
    original_path = manifest["members"][0]["path"]
    if path_variant == "dot-segment":
        noncanonical_path = f"./{original_path}"
    else:
        first_component, remainder = original_path.split("/", maxsplit=1)
        noncanonical_path = f"{first_component}//{remainder}"
    manifest["members"][0]["path"] = noncanonical_path

    with zipfile.ZipFile(pair_path, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info, data in entries:
            if info.filename == original_path:
                info.filename = noncanonical_path
            elif info.filename == ARCHIVE_MANIFEST_FILENAME:
                data = json.dumps(manifest).encode("utf-8")
            target.writestr(info, data)

    summary_path = job.config.output_dir / SUMMARY_FILENAME
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["output_bytes"] = sum(
        archive.output_path.stat().st_size for archive in job.plan.archives
    )
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    result = verify_job(job.config.output_dir, job.inventory)

    assert result.valid is False
    assert result.issues
