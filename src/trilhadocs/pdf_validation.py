from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


class PdfValidationError(ValueError):
    """A PDF is unreadable, encrypted or has no pages."""


def validate_pdf(path: Path) -> int:
    try:
        with Path(path).open("rb") as source:
            reader = PdfReader(source, strict=True)
            if reader.is_encrypted:
                raise PdfValidationError("PDF criptografado não pode ser validado.")
            page_count = len(reader.pages)
            if page_count < 1:
                raise PdfValidationError("PDF deve conter pelo menos uma página.")
            for page in reader.pages:
                _ = page.mediabox
    except PdfValidationError:
        raise
    except Exception:
        raise PdfValidationError("PDF inválido ou ilegível.") from None

    return page_count
