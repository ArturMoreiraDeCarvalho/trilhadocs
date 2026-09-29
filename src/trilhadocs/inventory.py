from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from pydantic import TypeAdapter, ValidationError

from trilhadocs.models import AccountRecord, AttachmentRecord, InventoryRecord

_RECORD_ADAPTER = TypeAdapter(InventoryRecord)


class InventoryError(ValueError):
    """A safe, user-facing inventory validation failure."""


@dataclass(frozen=True, slots=True)
class Inventory:
    records: tuple[InventoryRecord, ...]
    sha256: str

    @property
    def accounts(self) -> Mapping[str, AccountRecord]:
        return MappingProxyType(
            {
                record.account_id: record
                for record in self.records
                if isinstance(record, AccountRecord)
            }
        )

    @property
    def attachments(self) -> tuple[AttachmentRecord, ...]:
        return tuple(record for record in self.records if isinstance(record, AttachmentRecord))


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _safe_validation_message(raw_record: object, line_number: int) -> str:
    if isinstance(raw_record, dict):
        record_type = raw_record.get("record_type")
        if not isinstance(record_type, str) or record_type not in ("account", "attachment"):
            return f"Tipo de registro desconhecido (linha {line_number})."
        if record_type == "account":
            status = raw_record.get("status")
            if not isinstance(status, str) or status not in ("completed", "pending"):
                return f"Status inválido (linha {line_number})."
            if status == "completed" and raw_record.get("cover") is None:
                return f"Conta concluída sem capa (linha {line_number})."
            if status == "pending" and raw_record.get("cover") is not None:
                return f"Conta pendente declara capa (linha {line_number})."
    return f"Registro de inventário inválido (linha {line_number})."


def load_inventory(path: Path) -> Inventory:
    digest = hashlib.sha256()
    records: list[InventoryRecord] = []

    try:
        with Path(path).open("rb") as source:
            for line_number, raw_line in enumerate(source, start=1):
                digest.update(raw_line)
                if not raw_line.strip():
                    continue
                try:
                    decoded = raw_line.decode("utf-8")
                    raw_record = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    raise InventoryError(
                        f"JSONL inválido no inventário (linha {line_number})."
                    ) from None
                try:
                    record = _RECORD_ADAPTER.validate_python(raw_record)
                except ValidationError:
                    raise InventoryError(
                        _safe_validation_message(raw_record, line_number)
                    ) from None
                records.append(record)
    except InventoryError:
        raise
    except (OSError, ValueError):
        raise InventoryError("Não foi possível ler o inventário local.") from None

    if not records:
        raise InventoryError("O inventário não contém registros.")

    inventory = Inventory(records=tuple(records), sha256=digest.hexdigest())
    validate_inventory(inventory)
    return inventory


def validate_inventory(inventory: Inventory) -> None:
    account_ids: set[str] = set()
    document_ids: set[str] = set()

    for record in inventory.records:
        if isinstance(record, AccountRecord):
            if record.account_id in account_ids:
                raise InventoryError("ID de conta duplicado no inventário.")
            account_ids.add(record.account_id)
            if record.status == "completed" and record.cover is None:
                raise InventoryError("Conta concluída sem capa.")
            if record.status == "pending" and record.cover is not None:
                raise InventoryError("Conta pendente declara capa.")
        elif isinstance(record, AttachmentRecord):
            if record.document_id in document_ids:
                raise InventoryError("ID de documento duplicado no inventário.")
            document_ids.add(record.document_id)
        else:
            raise InventoryError("Tipo de registro desconhecido no inventário.")

    for record in inventory.records:
        if isinstance(record, AttachmentRecord) and record.account_id not in account_ids:
            raise InventoryError("Anexo órfão no inventário.")
