from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
SourcePath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2048),
]
Filename = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-fA-F]{64}$"),
]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class FileRef(StrictRecord):
    source_path: SourcePath
    filename: Filename
    size_bytes: int = Field(ge=0, strict=True)
    sha256: Sha256Digest

    @field_validator("sha256")
    @classmethod
    def normalize_digest(cls, value: str) -> str:
        return value.lower()


class AccountRecord(StrictRecord):
    record_type: Literal["account"]
    account_id: Identifier
    company_id: Identifier
    company_name: Filename
    division_id: Identifier
    division_name: Filename
    period: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    account_code: Identifier
    account_name: Filename
    status: Literal["completed", "pending"]
    cover: FileRef | None = None

    @model_validator(mode="after")
    def validate_cover_status(self) -> AccountRecord:
        if self.status == "completed" and self.cover is None:
            raise ValueError("Conta concluída exige uma referência de capa.")
        if self.status == "pending" and self.cover is not None:
            raise ValueError("Conta pendente não pode declarar uma capa concluída.")
        return self


class AttachmentRecord(FileRef):
    record_type: Literal["attachment"]
    document_id: Identifier
    account_id: Identifier


InventoryRecord = Annotated[
    AccountRecord | AttachmentRecord,
    Field(discriminator="record_type"),
]
