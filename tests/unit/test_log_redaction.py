from __future__ import annotations

import json
from pathlib import Path

from trilhadocs.journal import append_event, read_journal
from trilhadocs.privacy import redact_sensitive_data


def test_redact_sensitive_fields_and_patterns_recursively() -> None:
    payload = {
        "message": (
            "Contact qa@example.invalid; CPF 123.456.789-09; "
            "CNPJ 12.345.678/0001-95; tel +55 11 91234-5678; "
            "path C:\\Demo\\Input\\invoice.pdf; token=synthetic-token-123"
        ),
        "account_name": "Synthetic Example Ltd",
        "name": "Synthetic Demo Contact",
        "filename": "synthetic-document.pdf",
        "nested": {"source_path": "/tmp/trilhadocs/input.pdf", "member_count": 2},
        "archive_index": 0,
        "plan_sha256": "a" * 64,
    }

    redacted = redact_sensitive_data(payload)

    assert redacted == {
        "message": (
            "Contact [REDACTED]; CPF [REDACTED]; CNPJ [REDACTED]; "
            "tel [REDACTED]; path [REDACTED]; token=[REDACTED]"
        ),
        "account_name": "[REDACTED]",
        "name": "[REDACTED]",
        "filename": "[REDACTED]",
        "nested": {"source_path": "[REDACTED]", "member_count": 2},
        "archive_index": 0,
        "plan_sha256": "a" * 64,
    }


def test_journal_redacts_sensitive_job_id_and_preserves_checkpoint_bytes(
    tmp_path: Path,
) -> None:
    journal_path = tmp_path / "audit.jsonl"
    append_event(
        journal_path,
        {
            "event": "START",
            "job_id": "qa@example.invalid",
            "plan_sha256": "a" * 64,
            "inventory_sha256": "b" * 64,
            "archive_count": 1,
            "master_expected": False,
        },
    )
    append_event(
        journal_path,
        {
            "event": "ARCHIVE_VERIFIED",
            "archive_index": 0,
            "sha256": "c" * 64,
            "size_bytes": 123,
        },
    )

    lines = journal_path.read_bytes().splitlines()
    state = read_journal(journal_path)

    assert b"qa@example.invalid" not in journal_path.read_bytes()
    assert json.loads(lines[0])["job_id"] == "[REDACTED]"
    assert lines[1] == (
        b'{"archive_index":0,"event":"ARCHIVE_VERIFIED","sha256":"'
        + b"c" * 64
        + b'","size_bytes":123}'
    )
    assert state.job_id == "[REDACTED]"
    assert state.plan_sha256 == "a" * 64
    assert state.inventory_sha256 == "b" * 64
    assert state.archives[0]["sha256"] == "c" * 64
    assert state.archives[0]["size_bytes"] == 123


def test_redact_preserves_generated_hexadecimal_job_id() -> None:
    job_id = "1234567890abcdef1234567890abcdef"

    assert redact_sensitive_data({"job_id": job_id}) == {"job_id": job_id}
