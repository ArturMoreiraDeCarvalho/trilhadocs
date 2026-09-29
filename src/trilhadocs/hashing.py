from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class ContentMismatchError(ValueError):
    """Source content could not be verified against its inventory record."""


@dataclass(frozen=True, slots=True)
class FileEvidence:
    size_bytes: int
    sha256: str


def inspect_file(path: Path, expected_size: int, expected_sha256: str) -> FileEvidence:
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
        or not isinstance(expected_sha256, str)
        or _SHA256_PATTERN.fullmatch(expected_sha256) is None
    ):
        raise ContentMismatchError("O tamanho ou SHA-256 esperado é inválido.")

    hasher = hashlib.sha256()
    size_bytes = 0
    try:
        with Path(path).open("rb") as source:
            while chunk := source.read(_CHUNK_SIZE):
                hasher.update(chunk)
                size_bytes += len(chunk)
    except (OSError, ValueError):
        raise ContentMismatchError("Não foi possível verificar o conteúdo de origem.") from None

    actual_sha256 = hasher.hexdigest()
    if size_bytes != expected_size or actual_sha256 != expected_sha256.lower():
        raise ContentMismatchError("Tamanho ou SHA-256 do arquivo não corresponde ao inventário.")

    return FileEvidence(size_bytes=size_bytes, sha256=actual_sha256)
