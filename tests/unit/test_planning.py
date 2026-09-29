from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from trilhadocs.config import ProjectConfig
from trilhadocs.inventory import Inventory
from trilhadocs.models import AccountRecord, AttachmentRecord, FileRef
from trilhadocs.planning import (
    PlanningError,
    PreflightError,
    build_member_plan,
    preflight,
)


def file_ref(filename: str, source_path: str, contents: bytes) -> FileRef:
    return FileRef(
        source_path=source_path,
        filename=filename,
        size_bytes=len(contents),
        sha256=sha256(contents).hexdigest(),
    )


def account(
    account_id: str = "demo-account-1",
    account_name: str = "Conta de caixa",
    *,
    account_code: str = "100200",
    period: str = "2026-06",
    company_id: str = "demo-company-1",
    company_name: str = "Empresa Demonstração",
    division_id: str = "demo-division-1",
    division_name: str = "Unidade Sintética",
    cover: bool = True,
) -> AccountRecord:
    return AccountRecord(
        record_type="account",
        account_id=account_id,
        company_id=company_id,
        company_name=company_name,
        division_id=division_id,
        division_name=division_name,
        period=period,
        account_code=account_code,
        account_name=account_name,
        status="completed" if cover else "pending",
        cover=(
            file_ref("Capa.pdf", f"covers/{account_id}.pdf", b"synthetic cover") if cover else None
        ),
    )


def attachment(
    document_id: str,
    account_id: str,
    filename: str,
    source_path: str | None = None,
) -> AttachmentRecord:
    return AttachmentRecord(
        record_type="attachment",
        document_id=document_id,
        account_id=account_id,
        source_path=source_path or f"attachments/{document_id}.pdf",
        filename=filename,
        size_bytes=12,
        sha256=sha256(b"synthetic file").hexdigest(),
    )


def inventory(*records: AccountRecord | AttachmentRecord) -> Inventory:
    return Inventory(records=records, sha256="a" * 64)


def config(
    output_dir: Path,
    *,
    path_limit: int = 185,
    create_master: bool = True,
) -> ProjectConfig:
    return ProjectConfig(
        inventory_path=output_dir.parent / "inventory.jsonl",
        source_root=output_dir.parent / "sources",
        output_dir=output_dir,
        path_limit=path_limit,
        max_workers=2,
        create_master=create_master,
    )


def short_output_root(tmp_path: Path, label: str = "out") -> Path:
    return Path(tmp_path.anchor) / f"td-{tmp_path.name[-8:]}-{label}"


def path_units(path: Path) -> int:
    return len(str(path).encode("utf-16-le")) // 2


def test_build_member_plan_groups_pair_and_creates_readable_member_paths(
    tmp_path: Path,
) -> None:
    account_record = account()
    document = attachment("demo-document-1", account_record.account_id, "Invoice.pdf")
    output_dir = short_output_root(tmp_path, "output")

    plan = build_member_plan(config(output_dir), inventory(account_record, document))

    assert len(plan.archives) == 1
    archive = plan.archives[0]
    assert archive.filename == "Empresa Demonstração - Unidade Sintética.zip"
    members = {member.source_path: member for member in archive.members}
    assert members["covers/demo-account-1.pdf"].member_path == (
        "2026-06/100200 - Conta de caixa/Capa/Capa.pdf"
    )
    assert members["attachments/demo-document-1.pdf"].member_path == (
        "2026-06/100200 - Conta de caixa/Anexos/Invoice.pdf"
    )
    assert plan.master_filename == "trilhadocs-pacotes.zip"
    assert all(member.extraction_path.is_absolute() for member in archive.members)
    assert all("demo-account-1" not in member.member_path for member in archive.members)


def test_build_member_plan_truncates_only_the_account_name_tail(tmp_path: Path) -> None:
    long_name = "Identifiable checking account " + "with historical notes " * 7
    account_record = account(account_name=long_name)
    output_dir = short_output_root(tmp_path)

    plan = build_member_plan(config(output_dir), inventory(account_record))
    member = plan.archives[0].members[0]
    folder = member.member_path.split("/")[1]

    assert folder.startswith("100200 - Identifiable checking account")
    assert folder != f"100200 - {long_name}"
    assert "demo-account-1" not in folder
    assert path_units(member.extraction_path) <= 185


def test_collisions_after_windows_sanitization_get_deterministic_suffixes(
    tmp_path: Path,
) -> None:
    first = account("account-a", "Cash/Reserve")
    second = account("account-z", "Cash?Reserve")
    output_dir = short_output_root(tmp_path)

    forward = build_member_plan(config(output_dir), inventory(first, second))
    reverse = build_member_plan(config(output_dir), inventory(second, first))

    def account_folders(plan) -> set[str]:
        return {member.member_path.split("/")[1] for member in plan.archives[0].members}

    expected = {"100200 - Cash_Reserve", "100200 - Cash_Reserve (2)"}
    assert account_folders(forward) == expected
    assert account_folders(reverse) == expected


def test_attachment_filename_collisions_are_resolved_without_ids(tmp_path: Path) -> None:
    account_record = account()
    documents = (
        attachment("doc-a", account_record.account_id, "Evidence.pdf"),
        attachment("doc-z", account_record.account_id, "evidence.PDF"),
    )

    plan = build_member_plan(
        config(short_output_root(tmp_path)), inventory(account_record, *documents)
    )
    members = {member.source_path: member.member_path for member in plan.archives[0].members}

    assert members["attachments/doc-a.pdf"].endswith("/Anexos/Evidence.pdf")
    assert members["attachments/doc-z.pdf"].endswith("/Anexos/evidence (2).PDF")
    assert all("doc-" not in path for path in members.values())


def test_preflight_rejects_an_attachment_path_that_cannot_fit(tmp_path: Path) -> None:
    account_record = account()
    long_filename = "e" * 170 + ".pdf"
    document = attachment("long-doc", account_record.account_id, long_filename)
    plan = build_member_plan(
        config(short_output_root(tmp_path)), inventory(account_record, document)
    )

    with pytest.raises(PreflightError, match="185"):
        preflight(plan, free_bytes=plan.required_bytes)


def test_preflight_enforces_exact_path_limit_and_free_space_without_writing(
    tmp_path: Path,
) -> None:
    output_root = Path(tmp_path.anchor) / "x"
    base = build_member_plan(config(output_root), inventory(account()))
    base_path_units = max(path_units(member.extraction_path) for member in base.archives[0].members)
    padding = 185 - base_path_units
    exact_root = Path(tmp_path.anchor) / ("x" * (padding + 1))
    plan = build_member_plan(config(exact_root), inventory(account()))

    assert plan.max_path_chars == 185
    result = preflight(plan, free_bytes=plan.required_bytes)
    assert result.required_bytes == plan.required_bytes
    assert result.free_bytes == plan.required_bytes
    assert result.max_path_chars == 185
    with pytest.raises(PreflightError):
        preflight(plan, free_bytes=plan.required_bytes - 1)
    with pytest.raises(PreflightError):
        preflight(replace(plan, path_limit=184), free_bytes=plan.required_bytes)
    assert not exact_root.exists()


def test_preflight_detects_duplicate_archive_member_paths(tmp_path: Path) -> None:
    account_record = account()
    document = attachment("duplicate-doc", account_record.account_id, "Other.pdf")
    plan = build_member_plan(
        config(short_output_root(tmp_path)), inventory(account_record, document)
    )
    archive = plan.archives[0]
    duplicate = replace(archive.members[1], member_path=archive.members[0].member_path)
    invalid_archive = replace(archive, members=(archive.members[0], duplicate))
    invalid_plan = replace(plan, archives=(invalid_archive,))

    with pytest.raises(PreflightError):
        preflight(invalid_plan, free_bytes=plan.required_bytes)


def test_build_member_plan_rejects_inconsistent_pair_labels(tmp_path: Path) -> None:
    first = account("account-a", company_name="Demo Company")
    second = account("account-b", company_name="Different Company")

    with pytest.raises(PlanningError):
        build_member_plan(config(short_output_root(tmp_path)), inventory(first, second))


def test_preview_and_preflight_do_not_create_output_directory(tmp_path: Path) -> None:
    output_dir = short_output_root(tmp_path, "not-created")
    plan = build_member_plan(config(output_dir), inventory(account()))

    preflight(plan, free_bytes=plan.required_bytes)

    assert not output_dir.exists()


def test_path_length_counts_supplementary_unicode_as_utf16_units(tmp_path: Path) -> None:
    account_record = account(account_name="Cash 💼 account")
    plan = build_member_plan(config(short_output_root(tmp_path)), inventory(account_record))
    longest = max(path_units(member.extraction_path) for member in plan.archives[0].members)

    assert plan.max_path_chars == longest
