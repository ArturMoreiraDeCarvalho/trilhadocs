from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath

_INVALID_WINDOWS_CHARS = frozenset('<>:"/\\|?*')
_RESERVED_WINDOWS_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$",
    re.IGNORECASE,
)


class SourcePathError(ValueError):
    """A source path is invalid or not contained in its configured root."""


def safe_windows_component(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("O nome do componente deve ser texto.")

    normalized = unicodedata.normalize("NFC", value)
    sanitized = "".join(
        "_"
        if ord(char) < 32 or char in _INVALID_WINDOWS_CHARS or unicodedata.category(char) == "Cs"
        else char
        for char in normalized
    )
    sanitized = sanitized.strip().rstrip(" .")
    if not sanitized:
        sanitized = "_"

    device_stem = sanitized.split(".", maxsplit=1)[0].rstrip(" .")
    if _RESERVED_WINDOWS_NAME.fullmatch(device_stem):
        sanitized = f"_{sanitized}"
    return sanitized


def resolve_source(root: Path, relative_path: str) -> Path:
    if (
        not isinstance(relative_path, str)
        or not relative_path
        or "\x00" in relative_path
        or "\\" in relative_path
        or ":" in relative_path
    ):
        raise SourcePathError("Caminho de origem inválido ou fora da raiz permitida.")

    posix_path = PurePosixPath(relative_path)
    windows_path = PureWindowsPath(relative_path)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise SourcePathError("Caminho de origem inválido ou fora da raiz permitida.")
    if any(part in {"", ".", ".."} for part in relative_path.split("/")):
        raise SourcePathError("Caminho de origem inválido ou fora da raiz permitida.")

    try:
        resolved_root = Path(root).resolve(strict=True)
        if not resolved_root.is_dir():
            raise SourcePathError("Raiz de origem inválida.")
        resolved_source = (resolved_root / posix_path).resolve(strict=True)
        if not resolved_source.is_relative_to(resolved_root) or not resolved_source.is_file():
            raise SourcePathError("Caminho de origem inválido ou fora da raiz permitida.")
        return resolved_source
    except SourcePathError:
        raise
    except (OSError, RuntimeError, ValueError):
        raise SourcePathError("Caminho de origem inválido ou fora da raiz permitida.") from None
