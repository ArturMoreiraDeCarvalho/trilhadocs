from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trilhadocs.privacy import redact_sensitive_data


class JournalError(ValueError):
    """The local append-only build journal is invalid or inconsistent."""


@dataclass(frozen=True, slots=True)
class JournalState:
    job_id: str
    plan_sha256: str
    inventory_sha256: str
    archive_count: int
    master_expected: bool
    archives: dict[int, dict[str, Any]]
    master: dict[str, Any] | None
    complete: dict[str, Any] | None
    events: tuple[dict[str, Any], ...]


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _encode_event(event: dict[str, Any]) -> bytes:
    try:
        line = json.dumps(
            redact_sensitive_data(event),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        raise JournalError("Evento de journal inválido.") from None
    return (line + "\n").encode("utf-8")


def _write_new(path: Path, event: dict[str, Any]) -> None:
    try:
        with Path(path).open("xb") as journal:
            journal.write(_encode_event(event))
            journal.flush()
            os.fsync(journal.fileno())
    except FileExistsError:
        raise JournalError("O journal já existe para esta saída.") from None
    except OSError:
        raise JournalError("Não foi possível criar o journal local.") from None


def _reject_symlink(path: Path) -> Path:
    candidate = Path(path)
    if candidate.is_symlink():
        raise JournalError("O caminho do journal não pode ser link simbólico.")
    return candidate


def create_journal(
    path: Path,
    *,
    plan_sha256: str,
    inventory_sha256: str,
    archive_count: int,
    master_expected: bool,
) -> str:
    job_id = uuid.uuid4().hex
    event = {
        "event": "START",
        "job_id": job_id,
        "plan_sha256": plan_sha256,
        "inventory_sha256": inventory_sha256,
        "archive_count": archive_count,
        "master_expected": master_expected,
    }
    _write_new(path, event)
    return job_id


def append_event(path: Path, event: dict[str, Any]) -> None:
    candidate = _reject_symlink(path)
    try:
        with candidate.open("ab") as journal:
            journal.write(_encode_event(event))
            journal.flush()
            os.fsync(journal.fileno())
    except OSError:
        raise JournalError("Não foi possível registrar o checkpoint local.") from None


def read_journal(path: Path) -> JournalState:
    candidate = _reject_symlink(path)
    try:
        raw = candidate.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            raise JournalError("O journal está incompleto ou vazio.")
        decoded = raw.decode("utf-8")
        parsed = [json.loads(line, object_pairs_hook=_json_object) for line in decoded.splitlines()]
    except JournalError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise JournalError("O journal local está inválido ou ilegível.") from None

    if not parsed or not all(isinstance(event, dict) for event in parsed):
        raise JournalError("O journal local não contém eventos válidos.")

    start = parsed[0]
    start_keys = {
        "event",
        "job_id",
        "plan_sha256",
        "inventory_sha256",
        "archive_count",
        "master_expected",
    }
    if (
        set(start) != start_keys
        or start.get("event") != "START"
        or not isinstance(start.get("job_id"), str)
        or not start["job_id"]
        or not _is_digest(start.get("plan_sha256"))
        or not _is_digest(start.get("inventory_sha256"))
        or isinstance(start.get("archive_count"), bool)
        or not isinstance(start.get("archive_count"), int)
        or start["archive_count"] < 0
        or not isinstance(start.get("master_expected"), bool)
    ):
        raise JournalError("O evento inicial do journal está inválido.")

    archive_count = start["archive_count"]
    master_expected = start["master_expected"]
    archives: dict[int, dict[str, Any]] = {}
    master: dict[str, Any] | None = None
    complete: dict[str, Any] | None = None

    for event in parsed[1:]:
        if complete is not None:
            raise JournalError("O journal contém eventos após COMPLETE.")
        if not isinstance(event.get("event"), str):
            raise JournalError("O journal contém um evento inválido.")

        event_type = event["event"]
        if event_type == "ARCHIVE_VERIFIED":
            if set(event) != {"event", "archive_index", "sha256", "size_bytes"}:
                raise JournalError("Checkpoint de ZIP inválido.")
            index = event.get("archive_index")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index < archive_count
                or index in archives
                or master is not None
                or not _is_digest(event.get("sha256"))
                or not _is_nonnegative_int(event.get("size_bytes"))
            ):
                raise JournalError("Checkpoint de ZIP inconsistente.")
            archives[index] = event
        elif event_type == "MASTER_VERIFIED":
            if (
                set(event) != {"event", "sha256", "size_bytes"}
                or not master_expected
                or master is not None
                or len(archives) != archive_count
                or not _is_digest(event.get("sha256"))
                or not _is_nonnegative_int(event.get("size_bytes"))
            ):
                raise JournalError("Checkpoint do ZIP mestre inconsistente.")
            master = event
        elif event_type == "COMPLETE":
            expected_keys = {"event", "summary_sha256", "archive_count", "member_count"}
            if (
                set(event) != expected_keys
                or len(archives) != archive_count
                or (master_expected and master is None)
                or not _is_digest(event.get("summary_sha256"))
                or not _is_nonnegative_int(event.get("archive_count"))
                or event.get("archive_count") != archive_count
                or not _is_nonnegative_int(event.get("member_count"))
            ):
                raise JournalError("Evento COMPLETE inconsistente.")
            complete = event
        else:
            raise JournalError("O journal contém um tipo de evento desconhecido.")

    return JournalState(
        job_id=start["job_id"],
        plan_sha256=start["plan_sha256"],
        inventory_sha256=start["inventory_sha256"],
        archive_count=archive_count,
        master_expected=master_expected,
        archives=archives,
        master=master,
        complete=complete,
        events=tuple(parsed),
    )


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value)


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
