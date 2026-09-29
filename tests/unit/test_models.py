import pytest
from pydantic import ValidationError

from trilhadocs.models import AccountRecord, AttachmentRecord, FileRef

GOOD_HASH = "a" * 64


def file_ref(**overrides: object) -> FileRef:
    values: dict[str, object] = {
        "source_path": "covers/account-1.pdf",
        "filename": "Capa.pdf",
        "size_bytes": 128,
        "sha256": GOOD_HASH,
    }
    values.update(overrides)
    return FileRef.model_validate(values)


def account(**overrides: object) -> AccountRecord:
    values: dict[str, object] = {
        "record_type": "account",
        "account_id": "account-1",
        "company_id": "company-1",
        "company_name": "Empresa Demonstração",
        "division_id": "division-1",
        "division_name": "Unidade Sintética",
        "period": "2026-06",
        "account_code": "111000",
        "account_name": "Banco de demonstração",
        "status": "completed",
        "cover": file_ref(),
    }
    values.update(overrides)
    return AccountRecord.model_validate(values)


def test_completed_account_requires_a_cover() -> None:
    with pytest.raises(ValidationError):
        account(cover=None)


def test_pending_account_cannot_claim_a_cover() -> None:
    with pytest.raises(ValidationError):
        account(status="pending", cover=file_ref())


def test_period_must_be_a_real_month() -> None:
    with pytest.raises(ValidationError):
        account(period="2026-13")


def test_status_is_restricted_to_supported_values() -> None:
    with pytest.raises(ValidationError):
        account(status="approved")


def test_file_ref_rejects_invalid_hash_and_negative_size() -> None:
    with pytest.raises(ValidationError):
        file_ref(sha256="not-a-digest")
    with pytest.raises(ValidationError):
        file_ref(size_bytes=-1)


def test_models_reject_extra_fields() -> None:
    with pytest.raises(ValidationError):
        account(unexpected="value")


def test_attachment_record_requires_unique_document_metadata() -> None:
    record = AttachmentRecord.model_validate(
        {
            "record_type": "attachment",
            "document_id": "doc-1",
            "account_id": "account-1",
            "source_path": "attachments/doc-1.pdf",
            "filename": "Documento.pdf",
            "size_bytes": 64,
            "sha256": GOOD_HASH,
        }
    )

    assert record.document_id == "doc-1"
    assert record.account_id == "account-1"
