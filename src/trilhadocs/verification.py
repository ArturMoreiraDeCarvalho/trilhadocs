from __future__ import annotations

import hashlib
import json
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from trilhadocs.inventory import Inventory, validate_inventory
from trilhadocs.models import AccountRecord, FileRef
from trilhadocs.paths import safe_windows_component

ARCHIVE_MANIFEST_FILENAME = "_trilhadocs-manifest.json"
MASTER_MANIFEST_FILENAME = "_trilhadocs-master-manifest.json"
SUMMARY_FILENAME = ".trilhadocs-summary.json"
MASTER_FILENAME = "trilhadocs-pacotes.zip"
_CHUNK_SIZE = 1024 * 1024
_NUMERIC_SUFFIX = re.compile(r" \(\d+\)$")


class _VerificationFailure(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerificationResult:
    valid: bool
    archive_count: int
    member_count: int
    output_bytes: int
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ExpectedMember:
    kind: str
    account_id: str
    document_id: str | None
    company_id: str
    division_id: str
    period: str
    account_code: str
    account_name: str
    filename: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class _Artifact:
    path: Path
    company_id: str
    division_id: str
    archive_index: int
    sha256: str
    size_bytes: int


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _read_json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _file_evidence(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("rb") as source:
        while chunk := source.read(_CHUNK_SIZE):
            digest.update(chunk)
            size_bytes += len(chunk)
    return digest.hexdigest(), size_bytes


def _member_evidence(archive: zipfile.ZipFile, filename: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size_bytes = 0
    with archive.open(filename, "r") as source:
        while chunk := source.read(_CHUNK_SIZE):
            digest.update(chunk)
            size_bytes += len(chunk)
    return digest.hexdigest(), size_bytes


def _safe_output_file(path: Path, output_dir: Path) -> Path:
    """Resolve a regular output file while keeping it inside the job directory."""
    try:
        if path.is_symlink() or not path.is_file():
            raise _VerificationFailure(
                "Um artefato de sa\u00edda n\u00e3o \u00e9 um arquivo regular."
            )
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(output_dir):
            raise _VerificationFailure("Um artefato de sa\u00edda est\u00e1 fora da pasta do job.")
        return resolved
    except _VerificationFailure:
        raise
    except OSError:
        raise _VerificationFailure(
            "N\u00e3o foi poss\u00edvel acessar um artefato de sa\u00edda."
        ) from None


def _validate_zip_entries(archive: zipfile.ZipFile) -> list[str]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    windows_names = [unicodedata.normalize("NFKC", name).casefold() for name in names]
    if len(windows_names) != len(set(windows_names)):
        raise _VerificationFailure("O ZIP cont\u00e9m nomes que colidem no Windows.")
    for info in infos:
        file_type = stat.S_IFMT(info.external_attr >> 16)
        if info.is_dir() or file_type not in (0, stat.S_IFREG):
            raise _VerificationFailure(
                "O ZIP cont\u00e9m uma entrada que n\u00e3o \u00e9 arquivo regular."
            )
    return names


def _read_expected(
    inventory: Inventory,
) -> tuple[set[tuple[str, str]], dict[tuple[str, str, str | None], _ExpectedMember]]:
    validate_inventory(inventory)
    if not _is_digest(inventory.sha256):
        raise _VerificationFailure("O hash do inventário esperado é inválido.")
    accounts = inventory.accounts
    pairs = {(account.company_id, account.division_id) for account in accounts.values()}
    members: dict[tuple[str, str, str | None], _ExpectedMember] = {}
    for account in accounts.values():
        if account.cover is not None:
            key = ("cover", account.account_id, None)
            members[key] = _expected_member("cover", account, None, account.cover)
    for attachment in inventory.attachments:
        account = accounts[attachment.account_id]
        key = ("attachment", account.account_id, attachment.document_id)
        members[key] = _expected_member("attachment", account, attachment.document_id, attachment)
    return pairs, members


def _expected_member(
    kind: str,
    account: AccountRecord,
    document_id: str | None,
    file_ref: FileRef,
) -> _ExpectedMember:
    return _ExpectedMember(
        kind=kind,
        account_id=account.account_id,
        document_id=document_id,
        company_id=account.company_id,
        division_id=account.division_id,
        period=account.period,
        account_code=account.account_code,
        account_name=account.account_name,
        filename=file_ref.filename,
        size_bytes=file_ref.size_bytes,
        sha256=file_ref.sha256,
    )


def _safe_member_path(
    path: object,
    member: _ExpectedMember,
    master_created: bool,
    output_dir: Path,
    archive_path: Path,
    path_limit: int,
) -> bool:
    if not isinstance(path, str) or "\\" in path or ":" in path:
        return False
    relative = PurePosixPath(path)
    if (
        relative.as_posix() != path
        or relative.is_absolute()
        or len(relative.parts) != 4
        or any(part in {"", ".", ".."} for part in relative.parts)
        or any(safe_windows_component(part) != part for part in relative.parts)
    ):
        return False
    if relative.parts[0] != member.period:
        return False
    expected_category = "Capa" if member.kind == "cover" else "Anexos"
    if relative.parts[2] != expected_category:
        return False
    expected_prefix = f"{safe_windows_component(member.account_code)} - "
    folder = relative.parts[1]
    if not folder.casefold().startswith(expected_prefix.casefold()):
        return False
    visible_name = _NUMERIC_SUFFIX.sub("", folder[len(expected_prefix) :])
    safe_name = safe_windows_component(member.account_name)
    if not visible_name or not safe_name.casefold().startswith(visible_name.casefold()):
        return False
    expected_filename = safe_windows_component(member.filename)
    if relative.parts[3].casefold() != expected_filename.casefold():
        expected_path = PurePosixPath(expected_filename)
        actual_path = PurePosixPath(relative.parts[3])
        suffix = expected_path.suffix
        base = expected_path.name[: -len(suffix)] if suffix else expected_path.name
        if (
            actual_path.suffix.casefold() != suffix.casefold()
            or not actual_path.stem.casefold().startswith(base.casefold())
            or _NUMERIC_SUFFIX.sub("", actual_path.stem).casefold() != base.casefold()
        ):
            return False
    extraction_root = output_dir
    if master_created:
        extraction_root /= PurePosixPath(MASTER_FILENAME).stem
    extraction_root /= archive_path.stem
    full_path = extraction_root.joinpath(*relative.parts)
    return len(str(full_path).encode("utf-16-le")) // 2 <= path_limit


def _verify_pair_archive(
    path: Path,
    archive_index: int,
    plan_sha256: str,
    inventory_sha256: str,
    expected_pair: tuple[str, str],
    expected_members: dict[tuple[str, str, str | None], _ExpectedMember],
    seen_members: set[tuple[str, str, str | None]],
    master_created: bool,
    output_dir: Path,
    path_limit: int,
) -> tuple[_Artifact, int]:
    path = _safe_output_file(path, output_dir)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            if archive.testzip() is not None:
                raise _VerificationFailure(
                    "Um ZIP de empresa/divisão falhou na conferência de CRC."
                )
            names = _validate_zip_entries(archive)
            if (
                names.count(ARCHIVE_MANIFEST_FILENAME) != 1
                or names[-1] != ARCHIVE_MANIFEST_FILENAME
                or len(names) != len(set(names))
            ):
                raise _VerificationFailure("A lista de membros de um ZIP diverge do manifest.")
            manifest = _read_json(archive.read(ARCHIVE_MANIFEST_FILENAME))
            if set(manifest) != {
                "schema_version",
                "archive_index",
                "company_id",
                "division_id",
                "plan_sha256",
                "inventory_sha256",
                "members",
            }:
                raise _VerificationFailure("O manifest de um ZIP tem campos inesperados.")
            if (
                isinstance(manifest["schema_version"], bool)
                or manifest["schema_version"] != 1
                or isinstance(manifest["archive_index"], bool)
                or not isinstance(manifest["archive_index"], int)
                or manifest["archive_index"] != archive_index
                or (manifest["company_id"], manifest["division_id"]) != expected_pair
                or manifest["plan_sha256"] != plan_sha256
                or manifest["inventory_sha256"] != inventory_sha256
                or not isinstance(manifest["members"], list)
            ):
                raise _VerificationFailure("O manifest de um ZIP não corresponde ao inventário.")

            listed_members = manifest["members"]
            expected_names = [item.get("path") for item in listed_members]
            if names != expected_names + [ARCHIVE_MANIFEST_FILENAME]:
                raise _VerificationFailure("A lista de membros de um ZIP diverge do manifest.")

            member_count = 0
            for item in listed_members:
                if not isinstance(item, dict) or set(item) != {
                    "path",
                    "account_id",
                    "document_id",
                    "kind",
                    "category",
                    "size_bytes",
                    "sha256",
                }:
                    raise _VerificationFailure("Um registro de membro no manifest é inválido.")
                key = (item["kind"], item["account_id"], item["document_id"])
                expected = expected_members.get(key)
                if expected is None or key in seen_members:
                    raise _VerificationFailure("A cobertura de documentos diverge do inventário.")
                if (
                    (expected.company_id, expected.division_id) != expected_pair
                    or item["category"] != ("Capa" if expected.kind == "cover" else "Anexos")
                    or not _is_nonnegative_int(item["size_bytes"])
                    or item["size_bytes"] != expected.size_bytes
                    or item["sha256"] != expected.sha256
                    or not _safe_member_path(
                        item["path"],
                        expected,
                        master_created,
                        output_dir,
                        path,
                        path_limit,
                    )
                ):
                    raise _VerificationFailure("Os metadados de um membro divergem do inventário.")
                if not _is_digest(item["sha256"]):
                    raise _VerificationFailure("O hash de um membro do manifest é inválido.")
                info = archive.getinfo(item["path"])
                if info.file_size != expected.size_bytes:
                    raise _VerificationFailure("O tamanho de um membro diverge do inventário.")
                digest, size_bytes = _member_evidence(archive, item["path"])
                if size_bytes != expected.size_bytes or digest != expected.sha256:
                    raise _VerificationFailure("O conteúdo de um membro diverge do inventário.")
                seen_members.add(key)
                member_count += 1
    except _VerificationFailure:
        raise
    except Exception:
        raise _VerificationFailure("Um ZIP de empresa/divisão está inválido ou ilegível.") from None

    digest, size_bytes = _file_evidence(path)
    return (
        _Artifact(
            path=path,
            company_id=expected_pair[0],
            division_id=expected_pair[1],
            archive_index=archive_index,
            sha256=digest,
            size_bytes=size_bytes,
        ),
        member_count,
    )


def _verify_master(
    path: Path,
    archives: dict[int, _Artifact],
    plan_sha256: str,
    inventory_sha256: str,
) -> int:
    ordered = [archives[index] for index in sorted(archives)]
    try:
        with zipfile.ZipFile(path, "r") as master:
            if master.testzip() is not None:
                raise _VerificationFailure("O ZIP mestre falhou na conferência de CRC.")
            names = _validate_zip_entries(master)
            expected_names = [artifact.path.name for artifact in ordered]
            expected_names.append(MASTER_MANIFEST_FILENAME)
            if names != expected_names or len(names) != len(set(names)):
                raise _VerificationFailure("A lista de pacotes no ZIP mestre diverge.")
            manifest = _read_json(master.read(MASTER_MANIFEST_FILENAME))
            expected_manifest = {
                "schema_version",
                "plan_sha256",
                "inventory_sha256",
                "archives",
            }
            if (
                set(manifest) != expected_manifest
                or isinstance(manifest["schema_version"], bool)
                or manifest["schema_version"] != 1
                or manifest["plan_sha256"] != plan_sha256
                or manifest["inventory_sha256"] != inventory_sha256
                or not isinstance(manifest["archives"], list)
                or len(manifest["archives"]) != len(ordered)
            ):
                raise _VerificationFailure("O manifest do ZIP mestre não corresponde ao build.")
            for artifact, item in zip(ordered, manifest["archives"], strict=True):
                if (
                    not isinstance(item, dict)
                    or not _is_nonnegative_int(item.get("size_bytes"))
                    or item
                    != {
                        "path": artifact.path.name,
                        "company_id": artifact.company_id,
                        "division_id": artifact.division_id,
                        "size_bytes": artifact.size_bytes,
                        "sha256": artifact.sha256,
                    }
                ):
                    raise _VerificationFailure("Um pacote listado no manifest mestre diverge.")
                digest, size_bytes = _member_evidence(master, artifact.path.name)
                if digest != artifact.sha256 or size_bytes != artifact.size_bytes:
                    raise _VerificationFailure("O conteúdo de um pacote no ZIP mestre diverge.")
    except _VerificationFailure:
        raise
    except Exception:
        raise _VerificationFailure("O ZIP mestre está inválido ou ilegível.") from None
    return path.stat().st_size


def _verify(output_dir: Path, inventory: Inventory) -> VerificationResult:
    pairs, expected_members = _read_expected(inventory)
    output = Path(output_dir).expanduser().resolve(strict=True)
    if not output.is_dir():
        raise _VerificationFailure("O destino de saída não é uma pasta.")

    try:
        summary_path = _safe_output_file(output / SUMMARY_FILENAME, output)
        summary = _read_json(summary_path.read_bytes())
    except Exception:
        raise _VerificationFailure("O resumo final está ausente ou inválido.") from None
    if set(summary) != {
        "schema_version",
        "status",
        "plan_sha256",
        "inventory_sha256",
        "master_created",
        "path_limit",
        "archive_count",
        "member_count",
        "output_bytes",
    }:
        raise _VerificationFailure("O resumo final tem campos inesperados.")
    if (
        isinstance(summary["schema_version"], bool)
        or summary["schema_version"] != 1
        or summary["status"] != "COMPLETE"
        or not _is_digest(summary["plan_sha256"])
        or summary["inventory_sha256"] != inventory.sha256
        or not isinstance(summary["master_created"], bool)
        or isinstance(summary["path_limit"], bool)
        or not isinstance(summary["path_limit"], int)
        or not 1 <= summary["path_limit"] <= 185
        or isinstance(summary["archive_count"], bool)
        or not isinstance(summary["archive_count"], int)
        or summary["archive_count"] != len(pairs)
        or isinstance(summary["member_count"], bool)
        or not isinstance(summary["member_count"], int)
        or summary["member_count"] != len(expected_members)
        or isinstance(summary["output_bytes"], bool)
        or not isinstance(summary["output_bytes"], int)
        or summary["output_bytes"] < 0
    ):
        raise _VerificationFailure("O resumo final diverge do inventário esperado.")

    master_path = output / MASTER_FILENAME
    master_created = summary["master_created"]
    if master_created:
        master_path = _safe_output_file(master_path, output)
    if master_created != master_path.is_file():
        raise _VerificationFailure("A presença do ZIP mestre diverge do resumo.")

    zip_paths = sorted(
        path for path in output.iterdir() if path.is_file() and path.suffix.casefold() == ".zip"
    )
    pair_paths = [path for path in zip_paths if path != master_path]
    expected_archive_total = len(pairs) + (1 if master_created else 0)
    if len(zip_paths) != expected_archive_total or len(pair_paths) != len(pairs):
        raise _VerificationFailure("A quantidade de ZIPs não corresponde ao inventário.")

    ordered_pairs = sorted(pairs)
    seen_pairs: set[tuple[str, str]] = set()
    seen_members: set[tuple[str, str, str | None]] = set()
    archives_by_index: dict[int, _Artifact] = {}
    member_count = 0
    for path in pair_paths:
        path = _safe_output_file(path, output)
        if safe_windows_component(path.name) != path.name or not path.name.casefold().endswith(
            ".zip"
        ):
            raise _VerificationFailure("Um nome de ZIP de empresa/divisão é inválido.")
        try:
            with zipfile.ZipFile(path, "r") as archive:
                manifest = _read_json(archive.read(ARCHIVE_MANIFEST_FILENAME))
            index = manifest.get("archive_index")
            pair = (manifest.get("company_id"), manifest.get("division_id"))
        except Exception:
            raise _VerificationFailure("Não foi possível ler um manifest de ZIP.") from None
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < len(ordered_pairs)
            or pair != ordered_pairs[index]
            or pair in seen_pairs
            or index in archives_by_index
        ):
            raise _VerificationFailure("O agrupamento de ZIPs diverge do inventário.")
        artifact, archive_members = _verify_pair_archive(
            path,
            index,
            summary["plan_sha256"],
            inventory.sha256,
            pair,
            expected_members,
            seen_members,
            master_created,
            output,
            summary["path_limit"],
        )
        seen_pairs.add(pair)
        archives_by_index[index] = artifact
        member_count += archive_members

    if seen_pairs != pairs or seen_members != set(expected_members):
        raise _VerificationFailure("A cobertura final diverge do inventário esperado.")

    master_bytes = 0
    if master_created:
        master_bytes = _verify_master(
            master_path,
            archives_by_index,
            summary["plan_sha256"],
            inventory.sha256,
        )
    output_bytes = (
        sum(artifact.size_bytes for artifact in archives_by_index.values()) + master_bytes
    )
    if summary["output_bytes"] != output_bytes:
        raise _VerificationFailure("O total de bytes no resumo final diverge dos artefatos.")
    return VerificationResult(
        valid=True,
        archive_count=len(pairs),
        member_count=member_count,
        output_bytes=output_bytes,
        issues=(),
    )


def verify_job(output_dir: Path, expected_inventory: Inventory) -> VerificationResult:
    """Reopen all ZIPs and compare their exact coverage and content to the inventory."""
    try:
        return _verify(output_dir, expected_inventory)
    except _VerificationFailure as error:
        return VerificationResult(False, 0, 0, 0, (str(error),))
    except Exception:
        return VerificationResult(False, 0, 0, 0, ("Não foi possível verificar o pacote local.",))
