from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from trilhadocs.config import ProjectConfig
from trilhadocs.inventory import Inventory
from trilhadocs.models import AccountRecord, AttachmentRecord, FileRef
from trilhadocs.packaging import PackagingError, build_job
from trilhadocs.planning import BuildPlan, build_member_plan

JOURNAL_FILENAME = ".trilhadocs-journal.jsonl"
SUMMARY_FILENAME = ".trilhadocs-summary.json"
ARCHIVE_MANIFEST_FILENAME = "_trilhadocs-manifest.json"
MASTER_MANIFEST_FILENAME = "_trilhadocs-master-manifest.json"


@dataclass
class JobFixture:
    config: ProjectConfig
    inventory: Inventory
    plan: BuildPlan
    expected_sources: dict[Path, bytes]


def pdf_bytes() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)
    return buffer.getvalue()


def fixture_job(
    tmp_path: Path,
    *,
    corrupt_second: bool = False,
    create_master: bool = True,
) -> JobFixture:
    source_root = tmp_path / "sources"
    suffix = hashlib.sha256(str(tmp_path).encode("utf-8")).hexdigest()[:8]
    output_dir = tmp_path.parent / f"td-{suffix}"
    config = ProjectConfig(
        inventory_path=tmp_path / "inventory.jsonl",
        source_root=source_root,
        output_dir=output_dir,
        path_limit=185,
        max_workers=2,
        create_master=create_master,
    )
    expected_sources: dict[Path, bytes] = {}
    records: list[AccountRecord | AttachmentRecord] = []

    for index, (company_id, company_name) in enumerate(
        (("company-a", "Synthetic Company A"), ("company-b", "Synthetic Company B")),
        start=1,
    ):
        account_id = f"account-{index}"
        cover_expected = pdf_bytes()
        attachment_expected = pdf_bytes()
        cover_relative = Path("covers") / f"{account_id}.pdf"
        attachment_relative = Path("attachments") / f"document-{index}.pdf"
        cover_actual = (
            b"corrupt synthetic source" if corrupt_second and index == 2 else cover_expected
        )
        for relative_path, contents in (
            (cover_relative, cover_actual),
            (attachment_relative, attachment_expected),
        ):
            full_path = source_root / relative_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(contents)
            expected_sources[full_path] = (
                cover_expected if relative_path == cover_relative else attachment_expected
            )

        cover = FileRef(
            source_path=cover_relative.as_posix(),
            filename="Cover.pdf",
            size_bytes=len(cover_expected),
            sha256=hashlib.sha256(cover_expected).hexdigest(),
        )
        records.append(
            AccountRecord(
                record_type="account",
                account_id=account_id,
                company_id=company_id,
                company_name=company_name,
                division_id=f"division-{index}",
                division_name="Synthetic Division",
                period="2026-06",
                account_code=f"10020{index}",
                account_name=f"Synthetic checking account {index}",
                status="completed",
                cover=cover,
            )
        )
        records.append(
            AttachmentRecord(
                record_type="attachment",
                document_id=f"document-{index}",
                account_id=account_id,
                source_path=attachment_relative.as_posix(),
                filename="Evidence.pdf",
                size_bytes=len(attachment_expected),
                sha256=hashlib.sha256(attachment_expected).hexdigest(),
            )
        )

    inventory = Inventory(records=tuple(records), sha256="c" * 64)
    plan = build_member_plan(config, inventory)
    return JobFixture(config, inventory, plan, expected_sources)


def journal_events(output_dir: Path) -> list[dict[str, object]]:
    journal_path = output_dir / JOURNAL_FILENAME
    return [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]


def write_journal_events(path: Path, events: list[dict[str, object]]) -> None:
    serialized_events = "".join(
        json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events
    )
    path.write_text(
        serialized_events,
        encoding="utf-8",
    )


def rewrite_zip_member_type(path: Path, member_path: str, file_type: int) -> bytes:
    buffer = BytesIO()
    with (
        zipfile.ZipFile(path, "r") as source,
        zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target,
    ):
        for info in source.infolist():
            rewritten = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            rewritten.compress_type = info.compress_type
            rewritten.create_system = info.create_system
            rewritten.external_attr = info.external_attr
            if info.filename == member_path:
                rewritten.create_system = 3
                rewritten.external_attr = (file_type | 0o644) << 16
            target.writestr(
                rewritten,
                source.read(info.filename),
                compress_type=info.compress_type,
                compresslevel=6,
            )
    rewritten_bytes = buffer.getvalue()
    path.write_bytes(rewritten_bytes)
    return rewritten_bytes


def source_snapshot(expected_sources: dict[Path, bytes]) -> dict[Path, str]:
    return {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in expected_sources}


def test_build_job_writes_verified_pair_archives_master_and_complete_summary(
    tmp_path: Path,
) -> None:
    job = fixture_job(tmp_path)
    before = source_snapshot(job.expected_sources)

    result = build_job(job.config, job.inventory, job.plan, resume=False)

    assert result.complete is True
    assert result.archive_count == 2
    assert result.member_count == 4
    assert source_snapshot(job.expected_sources) == before
    for archive_plan in job.plan.archives:
        with zipfile.ZipFile(archive_plan.output_path) as archive:
            assert archive.testzip() is None
            assert set(archive.namelist()) == {
                member.member_path for member in archive_plan.members
            } | {ARCHIVE_MANIFEST_FILENAME}
            manifest = json.loads(archive.read(ARCHIVE_MANIFEST_FILENAME))
            assert manifest["inventory_sha256"] == job.inventory.sha256
            assert manifest["members"] == [
                {
                    "path": member.member_path,
                    "account_id": member.account_id,
                    "document_id": member.document_id,
                    "kind": "cover" if member.document_id is None else "attachment",
                    "category": member.member_path.split("/")[2],
                    "size_bytes": member.size_bytes,
                    "sha256": member.sha256,
                }
                for member in archive_plan.members
            ]

    master_path = job.config.output_dir / (job.plan.master_filename or "")
    with zipfile.ZipFile(master_path) as master:
        assert master.testzip() is None
        assert set(master.namelist()) == {archive.filename for archive in job.plan.archives} | {
            MASTER_MANIFEST_FILENAME
        }

    summary = json.loads((job.config.output_dir / SUMMARY_FILENAME).read_text("utf-8"))
    assert summary["status"] == "COMPLETE"
    assert [event["event"] for event in journal_events(job.config.output_dir)][-1] == "COMPLETE"
    journal_text = (job.config.output_dir / JOURNAL_FILENAME).read_text("utf-8")
    assert str(job.config.output_dir) not in journal_text
    assert "Synthetic Company A" not in journal_text
    assert "account-1" not in journal_text
    assert build_job(job.config, job.inventory, job.plan, resume=True) == result


def test_build_job_refuses_existing_output_without_overwriting_it(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    conflict = job.plan.archives[0].output_path
    conflict.parent.mkdir(parents=True, exist_ok=True)
    conflict.write_bytes(b"pre-existing user file")

    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=False)

    assert conflict.read_bytes() == b"pre-existing user file"
    assert not (job.config.output_dir / JOURNAL_FILENAME).exists()
    assert not (job.config.output_dir / SUMMARY_FILENAME).exists()


def test_build_job_produces_identical_archives_for_the_same_snapshot(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    first = build_job(job.config, job.inventory, job.plan, resume=False)
    suffix = hashlib.sha256(f"{tmp_path}:repeat".encode()).hexdigest()[:8]
    second_config = job.config.model_copy(update={"output_dir": tmp_path.parent / f"td-{suffix}"})
    second_plan = build_member_plan(second_config, job.inventory)
    second = build_job(second_config, job.inventory, second_plan, resume=False)

    assert first.plan_sha256 == second.plan_sha256
    for first_archive, second_archive in zip(
        job.plan.archives,
        second_plan.archives,
        strict=True,
    ):
        first_digest = hashlib.sha256(first_archive.output_path.read_bytes()).hexdigest()
        second_digest = hashlib.sha256(second_archive.output_path.read_bytes()).hexdigest()
        assert first_digest == second_digest
    first_master = job.config.output_dir / (job.plan.master_filename or "")
    second_master = second_config.output_dir / (second_plan.master_filename or "")
    assert (
        hashlib.sha256(first_master.read_bytes()).hexdigest()
        == hashlib.sha256(second_master.read_bytes()).hexdigest()
    )


def test_build_job_skips_master_archive_when_configuration_disables_it(tmp_path: Path) -> None:
    job = fixture_job(tmp_path, create_master=False)

    result = build_job(job.config, job.inventory, job.plan, resume=False)

    assert result.complete is True
    assert not (job.config.output_dir / MASTER_MANIFEST_FILENAME).exists()
    assert "MASTER_VERIFIED" not in [
        event["event"] for event in journal_events(job.config.output_dir)
    ]


def test_failed_build_preserves_completed_checkpoint_and_resumes_without_premature_complete(
    tmp_path: Path,
) -> None:
    job = fixture_job(tmp_path, corrupt_second=True)
    sources_before = source_snapshot(job.expected_sources)
    first_archive = job.plan.archives[0].output_path

    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=False)

    first_checkpoint = hashlib.sha256(first_archive.read_bytes()).hexdigest()
    events_after_failure = [event["event"] for event in journal_events(job.config.output_dir)]
    assert "ARCHIVE_VERIFIED" in events_after_failure
    assert "COMPLETE" not in events_after_failure
    assert not (job.config.output_dir / (job.plan.master_filename or "")).exists()
    assert not (job.config.output_dir / SUMMARY_FILENAME).exists()
    assert source_snapshot(job.expected_sources) == sources_before

    # Repairing the synthetic fixture simulates a corrected source on a later resume.
    for source_path, expected_bytes in job.expected_sources.items():
        source_path.write_bytes(expected_bytes)

    result = build_job(job.config, job.inventory, job.plan, resume=True)

    assert result.complete is True
    assert hashlib.sha256(first_archive.read_bytes()).hexdigest() == first_checkpoint
    assert [event["event"] for event in journal_events(job.config.output_dir)][-1] == "COMPLETE"


def test_resume_rejects_a_tampered_checkpoint_without_replacing_or_completing(
    tmp_path: Path,
) -> None:
    job = fixture_job(tmp_path, corrupt_second=True)
    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=False)

    checkpoint = job.plan.archives[0].output_path
    checkpoint.write_bytes(checkpoint.read_bytes() + b"tampered")
    tampered_bytes = checkpoint.read_bytes()
    for source_path, expected_bytes in job.expected_sources.items():
        source_path.write_bytes(expected_bytes)

    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=True)

    assert checkpoint.read_bytes() == tampered_bytes
    assert "COMPLETE" not in [event["event"] for event in journal_events(job.config.output_dir)]
    assert not (job.config.output_dir / SUMMARY_FILENAME).exists()


@pytest.mark.parametrize(
    "file_type",
    (pytest.param(stat.S_IFLNK, id="symlink"), pytest.param(stat.S_IFIFO, id="non-regular")),
)
def test_resume_rejects_non_regular_unix_zip_member_metadata_before_completion(
    tmp_path: Path,
    file_type: int,
) -> None:
    job = fixture_job(tmp_path, corrupt_second=True)
    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=False)

    checkpoint = job.plan.archives[0].output_path
    member_path = job.plan.archives[0].members[0].member_path
    rewritten_bytes = rewrite_zip_member_type(checkpoint, member_path, file_type)
    journal_path = job.config.output_dir / JOURNAL_FILENAME
    events = journal_events(job.config.output_dir)
    checkpoint_event = next(
        event
        for event in events
        if event["event"] == "ARCHIVE_VERIFIED" and event["archive_index"] == 0
    )
    checkpoint_event["sha256"] = hashlib.sha256(rewritten_bytes).hexdigest()
    checkpoint_event["size_bytes"] = len(rewritten_bytes)
    write_journal_events(journal_path, events)
    journal_before_resume = journal_path.read_bytes()

    for source_path, expected_bytes in job.expected_sources.items():
        source_path.write_bytes(expected_bytes)

    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=True)

    assert checkpoint.read_bytes() == rewritten_bytes
    assert journal_path.read_bytes() == journal_before_resume
    assert "COMPLETE" not in [event["event"] for event in journal_events(job.config.output_dir)]
    assert not (job.config.output_dir / SUMMARY_FILENAME).exists()


def test_resume_rejects_symlinked_pair_archive_before_checkpointing_external_file(
    tmp_path: Path,
) -> None:
    job = fixture_job(tmp_path, corrupt_second=True)
    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=False)

    archive_path = job.plan.archives[0].output_path
    external_archive = tmp_path / "external-pair.zip"
    external_archive.write_bytes(archive_path.read_bytes())
    archive_path.unlink()
    journal_path = job.config.output_dir / JOURNAL_FILENAME
    events = journal_events(job.config.output_dir)
    events = [
        event
        for event in events
        if not (event["event"] == "ARCHIVE_VERIFIED" and event["archive_index"] == 0)
    ]
    write_journal_events(journal_path, events)
    journal_before_resume = journal_path.read_bytes()
    try:
        archive_path.symlink_to(external_archive)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"File symlinks are unavailable here: {error}")
    external_before_resume = external_archive.read_bytes()

    for source_path, expected_bytes in job.expected_sources.items():
        source_path.write_bytes(expected_bytes)

    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=True)

    assert archive_path.is_symlink()
    assert external_archive.read_bytes() == external_before_resume
    assert journal_path.read_bytes() == journal_before_resume


def test_resume_rejects_symlinked_master_archive_before_checkpointing_external_file(
    tmp_path: Path,
) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan, resume=False)

    master_path = job.config.output_dir / (job.plan.master_filename or "")
    external_master = tmp_path / "external-master.zip"
    external_master.write_bytes(master_path.read_bytes())
    master_path.unlink()
    journal_path = job.config.output_dir / JOURNAL_FILENAME
    events = [
        event
        for event in journal_events(job.config.output_dir)
        if event["event"] not in {"MASTER_VERIFIED", "COMPLETE"}
    ]
    write_journal_events(journal_path, events)
    journal_before_resume = journal_path.read_bytes()
    try:
        master_path.symlink_to(external_master)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"File symlinks are unavailable here: {error}")
    external_before_resume = external_master.read_bytes()

    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=True)

    assert master_path.is_symlink()
    assert external_master.read_bytes() == external_before_resume
    assert journal_path.read_bytes() == journal_before_resume


@pytest.mark.parametrize(
    "file_type",
    (pytest.param(stat.S_IFLNK, id="symlink"), pytest.param(stat.S_IFIFO, id="non-regular")),
)
def test_resume_rejects_non_regular_unix_master_member_before_complete(
    tmp_path: Path,
    file_type: int,
) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan, resume=False)

    master_path = job.config.output_dir / (job.plan.master_filename or "")
    master_member = job.plan.archives[0].filename
    rewritten_bytes = rewrite_zip_member_type(master_path, master_member, file_type)
    journal_path = job.config.output_dir / JOURNAL_FILENAME
    events = [
        event
        for event in journal_events(job.config.output_dir)
        if event["event"] not in {"MASTER_VERIFIED", "COMPLETE"}
    ]
    write_journal_events(journal_path, events)
    journal_before_resume = journal_path.read_bytes()
    summary_path = job.config.output_dir / SUMMARY_FILENAME
    summary_path.unlink()

    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=True)

    assert master_path.read_bytes() == rewritten_bytes
    assert journal_path.read_bytes() == journal_before_resume
    assert "COMPLETE" not in [event["event"] for event in journal_events(job.config.output_dir)]
    assert not summary_path.exists()


def test_resume_rejects_a_false_member_count_in_the_complete_journal(tmp_path: Path) -> None:
    job = fixture_job(tmp_path)
    build_job(job.config, job.inventory, job.plan, resume=False)
    journal_path = job.config.output_dir / JOURNAL_FILENAME
    events = journal_events(job.config.output_dir)
    events[-1]["member_count"] = 999
    tampered_journal = "".join(
        json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n" for event in events
    )
    journal_path.write_text(tampered_journal, encoding="utf-8")
    artifact_paths = [archive.output_path for archive in job.plan.archives]
    artifact_paths.append(job.config.output_dir / (job.plan.master_filename or ""))
    artifact_paths.append(job.config.output_dir / SUMMARY_FILENAME)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifact_paths}

    with pytest.raises(PackagingError):
        build_job(job.config, job.inventory, job.plan, resume=True)

    assert journal_path.read_text("utf-8") == tampered_journal
    assert {
        path: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifact_paths
    } == before
