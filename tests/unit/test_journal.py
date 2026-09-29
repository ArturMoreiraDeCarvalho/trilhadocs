from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from trilhadocs.journal import (
    JournalError,
    append_event,
    create_journal,
    read_journal,
)


def digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def mark_path_as_symlink(monkeypatch, link_path: Path) -> None:
    is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda candidate: candidate == link_path or is_symlink(candidate),
    )


def test_journal_round_trips_only_verified_checkpoints_and_complete(tmp_path: Path) -> None:
    journal_path = tmp_path / "audit.jsonl"
    job_id = create_journal(
        journal_path,
        plan_sha256=digest("plan"),
        inventory_sha256=digest("inventory"),
        archive_count=1,
        master_expected=True,
    )
    append_event(
        journal_path,
        {
            "event": "ARCHIVE_VERIFIED",
            "archive_index": 0,
            "sha256": digest("archive"),
            "size_bytes": 123,
        },
    )
    append_event(
        journal_path,
        {"event": "MASTER_VERIFIED", "sha256": digest("master"), "size_bytes": 456},
    )
    append_event(
        journal_path,
        {
            "event": "COMPLETE",
            "summary_sha256": digest("summary"),
            "archive_count": 1,
            "member_count": 2,
        },
    )

    state = read_journal(journal_path)

    assert state.job_id == job_id
    assert state.plan_sha256 == digest("plan")
    assert state.inventory_sha256 == digest("inventory")
    assert state.archives[0]["sha256"] == digest("archive")
    assert state.master is not None
    assert state.complete is not None
    assert [event["event"] for event in state.events] == [
        "START",
        "ARCHIVE_VERIFIED",
        "MASTER_VERIFIED",
        "COMPLETE",
    ]


def test_journal_rejects_truncated_last_event_without_repairing_it(tmp_path: Path) -> None:
    journal_path = tmp_path / "audit.jsonl"
    create_journal(
        journal_path,
        plan_sha256=digest("plan"),
        inventory_sha256=digest("inventory"),
        archive_count=1,
        master_expected=False,
    )
    original = journal_path.read_bytes()
    journal_path.write_bytes(original + b'{"event":"ARCHIVE_VERIFIED"')
    malformed = journal_path.read_bytes()

    with pytest.raises(JournalError):
        read_journal(journal_path)

    assert journal_path.read_bytes() == malformed


def test_journal_rejects_complete_before_all_archive_checkpoints(tmp_path: Path) -> None:
    journal_path = tmp_path / "audit.jsonl"
    create_journal(
        journal_path,
        plan_sha256=digest("plan"),
        inventory_sha256=digest("inventory"),
        archive_count=1,
        master_expected=False,
    )
    with journal_path.open("ab") as journal:
        journal.write(
            (
                json.dumps(
                    {
                        "event": "COMPLETE",
                        "summary_sha256": digest("summary"),
                        "archive_count": 1,
                        "member_count": 1,
                    }
                )
                + "\n"
            ).encode("utf-8")
        )

    with pytest.raises(JournalError):
        read_journal(journal_path)


def test_read_journal_rejects_symlink_before_reading_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external_journal = tmp_path / "external.jsonl"
    create_journal(
        external_journal,
        plan_sha256=digest("plan"),
        inventory_sha256=digest("inventory"),
        archive_count=1,
        master_expected=False,
    )
    journal_path = tmp_path / "journal.jsonl"
    journal_path.write_bytes(external_journal.read_bytes())
    mark_path_as_symlink(monkeypatch, journal_path)
    journal_before_read = journal_path.read_bytes()
    external_before_read = external_journal.read_bytes()

    with pytest.raises(JournalError):
        read_journal(journal_path)

    assert journal_path.read_bytes() == journal_before_read
    assert external_journal.read_bytes() == external_before_read


def test_append_event_rejects_symlink_before_modifying_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external_journal = tmp_path / "external.jsonl"
    create_journal(
        external_journal,
        plan_sha256=digest("plan"),
        inventory_sha256=digest("inventory"),
        archive_count=1,
        master_expected=False,
    )
    journal_path = tmp_path / "journal.jsonl"
    journal_path.write_bytes(external_journal.read_bytes())
    mark_path_as_symlink(monkeypatch, journal_path)
    journal_before_append = journal_path.read_bytes()
    external_before_append = external_journal.read_bytes()

    with pytest.raises(JournalError):
        append_event(
            journal_path,
            {
                "event": "ARCHIVE_VERIFIED",
                "archive_index": 0,
                "sha256": digest("archive"),
                "size_bytes": 123,
            },
        )

    assert journal_path.read_bytes() == journal_before_append
    assert external_journal.read_bytes() == external_before_append
