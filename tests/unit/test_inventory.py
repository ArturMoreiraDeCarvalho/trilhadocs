import hashlib
import json
from pathlib import Path

import pytest

from trilhadocs.inventory import InventoryError, load_inventory, validate_inventory


def account_record(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "record_type": "account",
        "account_id": "demo-account-1",
        "company_id": "demo-company-1",
        "company_name": "Empresa Demonstração",
        "division_id": "demo-division-1",
        "division_name": "Unidade Sintética",
        "period": "2026-06",
        "account_code": "100200",
        "account_name": "Conta de demonstração",
        "status": "completed",
        "cover": {
            "source_path": "covers/account-1.pdf",
            "filename": "Capa.pdf",
            "size_bytes": 9,
            "sha256": hashlib.sha256(b"cover-pdf").hexdigest(),
        },
    }
    values.update(overrides)
    return values


def attachment_record(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "record_type": "attachment",
        "document_id": "demo-document-1",
        "account_id": "demo-account-1",
        "source_path": "attachments/document-1.pdf",
        "filename": "Comprovante.pdf",
        "size_bytes": 12,
        "sha256": hashlib.sha256(b"attachment").hexdigest(),
    }
    values.update(overrides)
    return values


def write_jsonl(path: Path, *records: dict[str, object], suffix: bytes = b"") -> bytes:
    payload = (
        b"".join(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
            for record in records
        )
        + suffix
    )
    path.write_bytes(payload)
    return payload


def test_load_inventory_parses_exact_ids_and_hashes_original_bytes(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.jsonl"
    payload = write_jsonl(inventory_path, account_record(), attachment_record(), suffix=b"\n")

    inventory = load_inventory(inventory_path)

    assert set(inventory.accounts) == {"demo-account-1"}
    assert [item.document_id for item in inventory.attachments] == ["demo-document-1"]
    assert inventory.sha256 == hashlib.sha256(payload).hexdigest()
    assert validate_inventory(inventory) is None


@pytest.mark.parametrize(
    ("records", "diagnostic"),
    [
        ((account_record(), account_record()), "ID de conta duplicado"),
        (
            (account_record(), attachment_record(), attachment_record()),
            "ID de documento duplicado",
        ),
        ((account_record(), attachment_record(account_id="unknown-account")), "anexo órfão"),
        (({**account_record(), "record_type": "unknown"},), "tipo de registro desconhecido"),
        (({**account_record(), "status": "approved"},), "status inválido"),
        (({**account_record(), "cover": None},), "conta concluída sem capa"),
    ],
)
def test_load_inventory_rejects_invalid_records(
    tmp_path: Path, records: tuple[dict[str, object], ...], diagnostic: str
) -> None:
    inventory_path = tmp_path / "inventory.jsonl"
    payload = write_jsonl(inventory_path, *records)
    before = hashlib.sha256(payload).hexdigest()

    with pytest.raises(InventoryError) as error:
        load_inventory(inventory_path)

    assert diagnostic.lower() in str(error.value).lower()
    assert hashlib.sha256(inventory_path.read_bytes()).hexdigest() == before
    assert str(inventory_path) not in str(error.value)
    assert "demo-account-1" not in str(error.value)


def test_load_inventory_rejects_malformed_json_without_echoing_input(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.jsonl"
    secret_fragment = b'"sensitive-demo-label":'
    inventory_path.write_bytes(b'{"record_type":"account","sensitive-demo-label":\n')
    before = hashlib.sha256(inventory_path.read_bytes()).hexdigest()

    with pytest.raises(InventoryError) as error:
        load_inventory(inventory_path)

    assert secret_fragment.decode() not in str(error.value)
    assert str(inventory_path) not in str(error.value)
    assert hashlib.sha256(inventory_path.read_bytes()).hexdigest() == before


def test_load_inventory_rejects_blank_inventory(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.jsonl"
    inventory_path.write_bytes(b"\n  \n")

    with pytest.raises(InventoryError):
        load_inventory(inventory_path)


def test_load_inventory_errors_do_not_expose_missing_path(tmp_path: Path) -> None:
    missing = tmp_path / "private-folder" / "inventory.jsonl"

    with pytest.raises(InventoryError) as error:
        load_inventory(missing)

    assert str(missing) not in str(error.value)
