from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_JOB_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
_EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_CNPJ_PATTERN = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_CPF_PATTERN = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?55[\s.-]*)?(?:\(?\d{2}\)?[\s.-]*)?9?\d{4}[\s.-]?\d{4}(?!\d)"
)
_URL_PATTERN = re.compile(r"(?i)\b(?:https?|file)://[^\s\"'<>]+")
_BEARER_PATTERN = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b((?:api[_-]?key|token|secret|password|senha)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_UNC_PATH_PATTERN = re.compile(r"(?<!\w)(?:\\\\|//)[^\\/\s,;]+[\\/][^\\/\s,;]+[^\s,;]*")
_WINDOWS_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\"'<>|,;\r\n]*")
_POSIX_PATH_PATTERN = re.compile(r"(?<![\w:])/(?:[^/\s,;]+/)+[^\s,;]*")
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "authorization",
        "cookie",
        "cpf",
        "cnpj",
        "email",
        "e_mail",
        "password",
        "passwd",
        "secret",
        "token",
        "phone",
        "telephone",
        "telefone",
        "mobile",
        "name",
        "nome",
        "filename",
        "file_name",
        "path",
        "directory",
        "dir",
        "root",
        "url",
        "uri",
        "source",
        "account_id",
        "document_id",
        "company_id",
        "client_id",
        "user_id",
        "tenant_id",
    }
)
_SENSITIVE_FIELD_SUFFIXES = (
    "_authorization",
    "_cookie",
    "_cpf",
    "_cnpj",
    "_email",
    "_e_mail",
    "_password",
    "_passwd",
    "_secret",
    "_token",
    "_phone",
    "_telephone",
    "_telefone",
    "_mobile",
    "_name",
    "_nome",
    "_path",
    "_filename",
    "_file_name",
    "_directory",
    "_dir",
    "_root",
    "_url",
    "_uri",
)


def _is_sensitive_field(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    return normalized in _SENSITIVE_FIELD_NAMES or normalized.endswith(_SENSITIVE_FIELD_SUFFIXES)


def _redact_text(value: str) -> str:
    for pattern in (
        _URL_PATTERN,
        _BEARER_PATTERN,
        _EMAIL_PATTERN,
        _CNPJ_PATTERN,
        _CPF_PATTERN,
        _PHONE_PATTERN,
        _UNC_PATH_PATTERN,
        _WINDOWS_PATH_PATTERN,
        _POSIX_PATH_PATTERN,
    ):
        value = pattern.sub(REDACTED, value)

    return _SECRET_ASSIGNMENT_PATTERN.sub(lambda match: match.group(1) + REDACTED, value)


def redact_sensitive_data(value: Any) -> Any:
    """Return a recursively redacted copy suitable for structured local logs.

    This deterministic filter is a defense in depth for common sensitive patterns;
    it cannot identify every personal, confidential, or indirectly identifying value.
    """
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_sensitive_field(key):
                redacted[key] = REDACTED
            elif (
                isinstance(item, str)
                and isinstance(key, str)
                and key.casefold() == "job_id"
                and _JOB_ID_PATTERN.fullmatch(item)
            ) or (
                isinstance(item, str)
                and isinstance(key, str)
                and (key.casefold() == "sha256" or key.casefold().endswith("_sha256"))
                and _SHA256_PATTERN.fullmatch(item)
            ):
                redacted[key] = item
            else:
                redacted[key] = redact_sensitive_data(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value
