import hashlib
from pathlib import Path

import pytest
from pypdf import PdfWriter

from trilhadocs.pdf_validation import PdfValidationError, validate_pdf


def write_pdf(path: Path, *, pages: int = 1, password: str | None = None) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if password is not None:
        writer.encrypt(password)
    with path.open("wb") as output:
        writer.write(output)


def test_validate_pdf_accepts_structurally_valid_pdf_and_returns_page_count(
    tmp_path: Path,
) -> None:
    source = tmp_path / "valid-synthetic.pdf"
    write_pdf(source, pages=2)

    assert validate_pdf(source) == 2


@pytest.mark.parametrize("contents", [b"not a pdf", b"%PDF-1.7\ntruncated"])
def test_validate_pdf_rejects_malformed_pdf_without_echoing_path(
    tmp_path: Path, contents: bytes
) -> None:
    source = tmp_path / "private-synthetic-name.pdf"
    source.write_bytes(contents)
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(PdfValidationError) as error:
        validate_pdf(source)

    assert str(source) not in str(error.value)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_validate_pdf_rejects_empty_pdf(tmp_path: Path) -> None:
    source = tmp_path / "zero-page.pdf"
    write_pdf(source, pages=0)
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(PdfValidationError):
        validate_pdf(source)

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_validate_pdf_rejects_encrypted_pdf(tmp_path: Path) -> None:
    source = tmp_path / "encrypted.pdf"
    write_pdf(source, password="synthetic-password")
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(PdfValidationError):
        validate_pdf(source)

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
