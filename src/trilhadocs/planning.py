from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from trilhadocs.config import ProjectConfig
from trilhadocs.inventory import Inventory, validate_inventory
from trilhadocs.models import AccountRecord, AttachmentRecord, FileRef
from trilhadocs.paths import safe_windows_component

_MASTER_FILENAME = "trilhadocs-pacotes.zip"
_ZIP_ARCHIVE_OVERHEAD = 4096
# Includes central-directory and per-member manifest overhead at model field limits.
_ZIP_MEMBER_OVERHEAD = 16 * 1024
_DEFLATE_BLOCK_BYTES = 16 * 1024
_DEFLATE_WORST_CASE_PER_BLOCK = 5


class PlanningError(ValueError):
    """The inventory cannot be represented as a deterministic package plan."""


class PreflightError(ValueError):
    """A build plan exceeds path or disk-space constraints."""


@dataclass(frozen=True, slots=True)
class PlannedMember:
    account_id: str
    document_id: str | None
    source_path: str
    member_path: str
    extraction_path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArchivePlan:
    company_id: str
    division_id: str
    filename: str
    output_path: Path
    members: tuple[PlannedMember, ...]


@dataclass(frozen=True, slots=True)
class BuildPlan:
    output_dir: Path
    archives: tuple[ArchivePlan, ...]
    master_filename: str | None
    path_limit: int
    required_bytes: int
    max_path_chars: int


@dataclass(frozen=True, slots=True)
class PreflightResult:
    archive_count: int
    member_count: int
    required_bytes: int
    free_bytes: int
    max_path_chars: int


@dataclass(frozen=True, slots=True)
class _SourceMember:
    account_id: str
    document_id: str | None
    category: str
    file_ref: FileRef
    safe_filename: str


def _utf16_units(value: str | Path) -> int:
    return len(str(value).encode("utf-16-le")) // 2


def _windows_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _truncate_utf16(value: str, max_units: int) -> str:
    if max_units <= 0:
        return ""
    result: list[str] = []
    used = 0
    for char in value:
        units = _utf16_units(char)
        if used + units > max_units:
            break
        result.append(char)
        used += units
    return "".join(result)


def _with_numeric_suffix(filename: str, number: int) -> str:
    path = PurePosixPath(filename)
    stem = path.stem if path.suffix else filename
    suffix = path.suffix
    return f"{stem} ({number}){suffix}"


def _unique_filename(filename: str, used: set[str]) -> str:
    candidate = filename
    number = 2
    while _windows_key(candidate) in used:
        candidate = _with_numeric_suffix(filename, number)
        number += 1
    used.add(_windows_key(candidate))
    return candidate


def _ordered_source_members(
    account_record: AccountRecord,
    attachments: list[AttachmentRecord],
) -> tuple[_SourceMember, ...]:
    raw_members: list[_SourceMember] = []
    if account_record.cover is not None:
        raw_members.append(
            _SourceMember(
                account_id=account_record.account_id,
                document_id=None,
                category="Capa",
                file_ref=account_record.cover,
                safe_filename=safe_windows_component(account_record.cover.filename),
            )
        )
    raw_members.extend(
        _SourceMember(
            account_id=account_record.account_id,
            document_id=attachment_record.document_id,
            category="Anexos",
            file_ref=attachment_record,
            safe_filename=safe_windows_component(attachment_record.filename),
        )
        for attachment_record in sorted(attachments, key=lambda record: record.document_id)
    )

    used_names: dict[str, set[str]] = {"Capa": set(), "Anexos": set()}
    named_members: list[_SourceMember] = []
    for member in raw_members:
        filename = _unique_filename(member.safe_filename, used_names[member.category])
        named_members.append(
            _SourceMember(
                account_id=member.account_id,
                document_id=member.document_id,
                category=member.category,
                file_ref=member.file_ref,
                safe_filename=filename,
            )
        )
    return tuple(named_members)


def _account_folder(
    account_record: AccountRecord,
    members: tuple[_SourceMember, ...],
    extraction_root: Path,
    path_limit: int,
    used_folders: set[str],
) -> str:
    code_prefix = f"{safe_windows_component(account_record.account_code)} - "
    account_name = safe_windows_component(account_record.account_name)
    max_name_units = path_limit
    for member in members:
        probe = (
            extraction_root
            / account_record.period
            / f"{code_prefix}x"
            / member.category
            / member.safe_filename
        )
        max_name_units = min(max_name_units, path_limit - _utf16_units(probe) + 1)

    number = 1
    while True:
        collision_suffix = "" if number == 1 else f" ({number})"
        suffix_units = _utf16_units(collision_suffix)
        name_units = max(0, max_name_units - suffix_units)
        visible_name = _truncate_utf16(account_name, name_units) or "_"
        candidate = f"{code_prefix}{visible_name}{collision_suffix}"
        candidate_key = _windows_key(candidate)
        if candidate_key not in used_folders:
            used_folders.add(candidate_key)
            return candidate
        number += 1


def _compressed_upper_bound(size_bytes: int) -> int:
    block_count = (size_bytes + _DEFLATE_BLOCK_BYTES - 1) // _DEFLATE_BLOCK_BYTES
    return size_bytes + block_count * _DEFLATE_WORST_CASE_PER_BLOCK + 64


def _archive_size_upper_bound(members: tuple[PlannedMember, ...]) -> int:
    return _zip_size_upper_bound(member.size_bytes for member in members)


def _zip_size_upper_bound(sizes: Iterable[int]) -> int:
    size_list = tuple(sizes)
    return (
        _ZIP_ARCHIVE_OVERHEAD
        + len(size_list) * _ZIP_MEMBER_OVERHEAD
        + sum(_compressed_upper_bound(size_bytes) for size_bytes in size_list)
    )


def _assign_archive_filenames(
    pair_groups: dict[tuple[str, str], list[AccountRecord]],
) -> dict[tuple[str, str], str]:
    used_names: set[str] = set()
    filenames: dict[tuple[str, str], str] = {}
    for pair in sorted(pair_groups):
        records = pair_groups[pair]
        company_name = records[0].company_name
        division_name = records[0].division_name
        base = (
            f"{safe_windows_component(company_name)} - {safe_windows_component(division_name)}.zip"
        )
        filenames[pair] = _unique_filename(base, used_names)
    return filenames


def build_member_plan(config: ProjectConfig, inventory: Inventory) -> BuildPlan:
    validate_inventory(inventory)
    output_dir = Path(config.output_dir).expanduser().resolve(strict=False)
    path_limit = config.path_limit

    companies: dict[str, str] = {}
    pair_groups: dict[tuple[str, str], list[AccountRecord]] = {}
    for account_record in inventory.accounts.values():
        existing_company = companies.setdefault(
            account_record.company_id, account_record.company_name
        )
        if existing_company != account_record.company_name:
            raise PlanningError("Rótulos divergentes para a mesma empresa no inventário.")
        pair = (account_record.company_id, account_record.division_id)
        if (
            pair in pair_groups
            and pair_groups[pair][0].division_name != account_record.division_name
        ):
            raise PlanningError("Rótulos divergentes para a mesma divisão no inventário.")
        pair_groups.setdefault(pair, []).append(account_record)

    attachments_by_account: dict[str, list[AttachmentRecord]] = {}
    for attachment_record in inventory.attachments:
        attachments_by_account.setdefault(attachment_record.account_id, []).append(
            attachment_record
        )

    filenames = _assign_archive_filenames(pair_groups)
    master_filename = _MASTER_FILENAME if config.create_master else None
    master_stem = PurePosixPath(master_filename).stem if master_filename else None
    archives: list[ArchivePlan] = []

    for pair in sorted(pair_groups):
        archive_filename = filenames[pair]
        archive_stem = PurePosixPath(archive_filename).stem
        extraction_root = output_dir
        if master_stem is not None:
            extraction_root = extraction_root / master_stem
        extraction_root = extraction_root / archive_stem

        account_folder_names: dict[str, str] = {}
        used_folders_by_period: dict[str, set[str]] = {}
        source_members_by_account: dict[str, tuple[_SourceMember, ...]] = {}
        for account_record in sorted(pair_groups[pair], key=lambda record: record.account_id):
            source_members = _ordered_source_members(
                account_record, attachments_by_account.get(account_record.account_id, [])
            )
            source_members_by_account[account_record.account_id] = source_members
            if not source_members:
                continue
            used_folders = used_folders_by_period.setdefault(account_record.period, set())
            account_folder_names[account_record.account_id] = _account_folder(
                account_record,
                source_members,
                extraction_root,
                path_limit,
                used_folders,
            )

        planned_members: list[PlannedMember] = []
        for account_record in sorted(pair_groups[pair], key=lambda record: record.account_id):
            account_folder = account_folder_names.get(account_record.account_id)
            if account_folder is None:
                continue
            for source_member in source_members_by_account[account_record.account_id]:
                relative_member_path = PurePosixPath(
                    account_record.period,
                    account_folder,
                    source_member.category,
                    source_member.safe_filename,
                )
                member_path = relative_member_path.as_posix()
                extraction_path = extraction_root.joinpath(*relative_member_path.parts)
                planned_members.append(
                    PlannedMember(
                        account_id=source_member.account_id,
                        document_id=source_member.document_id,
                        source_path=source_member.file_ref.source_path,
                        member_path=member_path,
                        extraction_path=extraction_path,
                        size_bytes=source_member.file_ref.size_bytes,
                        sha256=source_member.file_ref.sha256,
                    )
                )

        planned_members.sort(
            key=lambda member: (_windows_key(member.member_path), member.member_path)
        )
        archives.append(
            ArchivePlan(
                company_id=pair[0],
                division_id=pair[1],
                filename=archive_filename,
                output_path=output_dir / archive_filename,
                members=tuple(planned_members),
            )
        )

    max_path_chars = max(
        (
            _utf16_units(path)
            for archive in archives
            for path in (
                archive.output_path,
                *(member.extraction_path for member in archive.members),
            )
        ),
        default=0,
    )
    if master_filename is not None:
        max_path_chars = max(max_path_chars, _utf16_units(output_dir / master_filename))

    pair_archive_sizes = sum(_archive_size_upper_bound(archive.members) for archive in archives)
    required_bytes = pair_archive_sizes
    if master_filename is not None:
        required_bytes += _zip_size_upper_bound(
            _archive_size_upper_bound(archive.members) for archive in archives
        )

    return BuildPlan(
        output_dir=output_dir,
        archives=tuple(archives),
        master_filename=master_filename,
        path_limit=path_limit,
        required_bytes=required_bytes,
        max_path_chars=max_path_chars,
    )


def preflight(plan: BuildPlan, free_bytes: int) -> PreflightResult:
    if (
        isinstance(free_bytes, bool)
        or not isinstance(free_bytes, int)
        or free_bytes < 0
        or isinstance(plan.path_limit, bool)
        or not isinstance(plan.path_limit, int)
        or not 1 <= plan.path_limit <= 185
        or isinstance(plan.required_bytes, bool)
        or not isinstance(plan.required_bytes, int)
        or plan.required_bytes < 0
        or not plan.output_dir.is_absolute()
    ):
        raise PreflightError("Parâmetros de preflight inválidos.")

    archive_names: set[str] = set()
    output_paths: set[str] = set()
    extraction_paths: set[str] = set()
    recalculated_max_path = 0
    member_count = 0
    master_stem = PurePosixPath(plan.master_filename).stem if plan.master_filename else None

    if plan.master_filename is not None:
        if safe_windows_component(plan.master_filename) != plan.master_filename:
            raise PreflightError("Nome do ZIP mestre inválido para Windows.")
        master_path = plan.output_dir / plan.master_filename
        recalculated_max_path = max(recalculated_max_path, _utf16_units(master_path))
        if master_path.exists():
            raise PreflightError("O ZIP mestre já existe.")
        output_paths.add(_windows_key(str(master_path)))

    for archive in plan.archives:
        if safe_windows_component(
            archive.filename
        ) != archive.filename or not archive.filename.lower().endswith(".zip"):
            raise PreflightError("Nome de ZIP inválido para Windows.")
        archive_key = _windows_key(archive.filename)
        output_key = _windows_key(str(archive.output_path))
        if archive_key in archive_names or output_key in output_paths:
            raise PreflightError("Há colisão entre os ZIPs planejados.")
        archive_names.add(archive_key)
        output_paths.add(output_key)
        if _windows_key(str(archive.output_path)) != _windows_key(
            str(plan.output_dir / archive.filename)
        ):
            raise PreflightError("Caminho de saída do ZIP não corresponde ao plano.")

        recalculated_max_path = max(recalculated_max_path, _utf16_units(archive.output_path))
        if archive.output_path.exists():
            raise PreflightError("Um ZIP de saída já existe.")
        archive_stem = PurePosixPath(archive.filename).stem
        expected_root = plan.output_dir
        if master_stem is not None:
            expected_root = expected_root / master_stem
        expected_root = expected_root / archive_stem

        member_names: set[str] = set()
        for member in archive.members:
            member_count += 1
            relative_path = PurePosixPath(member.member_path)
            if (
                relative_path.is_absolute()
                or not relative_path.parts
                or any(part in {"", ".", ".."} for part in relative_path.parts)
                or "\\" in member.member_path
                or ":" in member.member_path
                or any(safe_windows_component(part) != part for part in relative_path.parts)
            ):
                raise PreflightError("Nome de membro inválido para Windows.")
            member_key = _windows_key(relative_path.as_posix())
            extraction_key = _windows_key(str(member.extraction_path))
            if member_key in member_names or extraction_key in extraction_paths:
                raise PreflightError("Há colisão entre membros planejados.")
            member_names.add(member_key)
            extraction_paths.add(extraction_key)

            expected_path = expected_root.joinpath(*relative_path.parts)
            if _windows_key(str(member.extraction_path)) != _windows_key(str(expected_path)):
                raise PreflightError("Caminho de extração não corresponde ao plano.")
            recalculated_max_path = max(recalculated_max_path, _utf16_units(expected_path))

    if recalculated_max_path != plan.max_path_chars:
        raise PreflightError("Comprimento do caminho não corresponde ao plano.")
    if recalculated_max_path > plan.path_limit:
        raise PreflightError(
            f"Caminho de extração excede o limite configurado de {plan.path_limit} caracteres."
        )
    if free_bytes < plan.required_bytes:
        raise PreflightError("Espaço livre insuficiente para criar os pacotes com segurança.")

    return PreflightResult(
        archive_count=len(plan.archives),
        member_count=member_count,
        required_bytes=plan.required_bytes,
        free_bytes=free_bytes,
        max_path_chars=recalculated_max_path,
    )
