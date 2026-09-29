from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from trilhadocs.config import ProjectConfig
from trilhadocs.inventory import Inventory, validate_inventory
from trilhadocs.journal import JournalState, append_event, create_journal, read_journal
from trilhadocs.paths import resolve_source
from trilhadocs.pdf_validation import validate_pdf
from trilhadocs.planning import (
    ArchivePlan,
    BuildPlan,
    PlannedMember,
    PreflightError,
    build_member_plan,
    preflight,
)

JOURNAL_FILENAME = ".trilhadocs-journal.jsonl"
SUMMARY_FILENAME = ".trilhadocs-summary.json"
ARCHIVE_MANIFEST_FILENAME = "_trilhadocs-manifest.json"
MASTER_MANIFEST_FILENAME = "_trilhadocs-master-manifest.json"
_CHUNK_SIZE = 1024 * 1024
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class PackagingError(ValueError):
    """The package build could not safely complete or resume."""


@dataclass(frozen=True, slots=True)
class ArtifactEvidence:
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class BuildResult:
    complete: bool
    archive_count: int
    member_count: int
    output_bytes: int
    plan_sha256: str


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _plan_digest(plan: BuildPlan, inventory: Inventory) -> str:
    archives: list[dict[str, Any]] = []
    for index, archive in enumerate(plan.archives):
        archives.append(
            {
                "index": index,
                "company_id": archive.company_id,
                "division_id": archive.division_id,
                "filename": archive.filename,
                "members": [
                    {
                        "account_id": member.account_id,
                        "document_id": member.document_id,
                        "source_path": member.source_path,
                        "member_path": member.member_path,
                        "size_bytes": member.size_bytes,
                        "sha256": member.sha256,
                    }
                    for member in archive.members
                ],
            }
        )
    payload = {
        "schema_version": 1,
        "inventory_sha256": inventory.sha256,
        "archives": archives,
        "master_filename": plan.master_filename,
        "path_limit": plan.path_limit,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _member_manifest(member: PlannedMember) -> dict[str, object]:
    return {
        "path": member.member_path,
        "account_id": member.account_id,
        "document_id": member.document_id,
        "kind": "cover" if member.document_id is None else "attachment",
        "category": Path(member.member_path).parts[2],
        "size_bytes": member.size_bytes,
        "sha256": member.sha256,
    }


def _archive_manifest(
    archive: ArchivePlan,
    index: int,
    plan_sha256: str,
    inventory_sha256: str,
) -> bytes:
    return _canonical_json(
        {
            "schema_version": 1,
            "archive_index": index,
            "company_id": archive.company_id,
            "division_id": archive.division_id,
            "plan_sha256": plan_sha256,
            "inventory_sha256": inventory_sha256,
            "members": [_member_manifest(member) for member in archive.members],
        }
    )


def _master_manifest(
    plan: BuildPlan,
    plan_sha256: str,
    inventory_sha256: str,
    evidence: dict[int, ArtifactEvidence],
) -> bytes:
    return _canonical_json(
        {
            "schema_version": 1,
            "plan_sha256": plan_sha256,
            "inventory_sha256": inventory_sha256,
            "archives": [
                {
                    "path": archive.filename,
                    "company_id": archive.company_id,
                    "division_id": archive.division_id,
                    "size_bytes": evidence[index].size_bytes,
                    "sha256": evidence[index].sha256,
                }
                for index, archive in enumerate(plan.archives)
            ],
        }
    )


def _zip_info(filename: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename, date_time=_ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def _free_bytes(path: Path) -> int:
    candidate = Path(path)
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise PackagingError("Não foi possível verificar o espaço local.")
        candidate = parent
    if not candidate.is_dir():
        candidate = candidate.parent
    try:
        return shutil.disk_usage(candidate).free
    except OSError:
        raise PackagingError("Não foi possível verificar o espaço local.") from None


def _ensure_no_fresh_conflicts(plan: BuildPlan) -> None:
    output_dir = plan.output_dir
    if output_dir.exists() and not output_dir.is_dir():
        raise PackagingError("O destino de saída não é uma pasta.")
    reserved = [output_dir / JOURNAL_FILENAME, output_dir / SUMMARY_FILENAME]
    reserved.extend(archive.output_path for archive in plan.archives)
    if plan.master_filename is not None:
        reserved.append(output_dir / plan.master_filename)
    if any(path.exists() for path in reserved):
        raise PackagingError("Já existe um artefato no destino; a saída foi preservada.")


def _available_bytes(output_dir: Path) -> int:
    return _free_bytes(output_dir)


def _source_to_zip(source_path: Path, member: PlannedMember, target: BinaryIO) -> None:
    hasher = hashlib.sha256()
    size_bytes = 0
    with source_path.open("rb") as source:
        while chunk := source.read(_CHUNK_SIZE):
            target.write(chunk)
            hasher.update(chunk)
            size_bytes += len(chunk)
    if size_bytes != member.size_bytes or hasher.hexdigest() != member.sha256:
        raise PackagingError("Tamanho ou SHA-256 de uma fonte não corresponde ao inventário.")


def _create_temp_file(directory: Path, prefix: str) -> tuple[Path, BinaryIO]:
    try:
        descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
        return Path(name), os.fdopen(descriptor, "w+b")
    except OSError:
        raise PackagingError("Não foi possível criar um temporário local.") from None


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        raise PackagingError("Não foi possível sincronizar a pasta de saída.") from None


def _publish_no_replace(temporary: Path, destination: Path) -> None:
    if destination.exists():
        raise PackagingError("Um artefato de saída já existe e não será substituído.")
    try:
        # A hard link publishes the fully flushed file atomically and fails if the
        # destination appeared after the preflight; unlink only our private temp.
        os.link(temporary, destination)
        temporary.unlink()
        _sync_directory(destination.parent)
    except FileExistsError:
        raise PackagingError("Um artefato de saída já existe e não será substituído.") from None
    except OSError:
        raise PackagingError("Não foi possível publicar o artefato de saída.") from None


def _hash_file(path: Path) -> ArtifactEvidence:
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        with Path(path).open("rb") as source:
            while chunk := source.read(_CHUNK_SIZE):
                digest.update(chunk)
                size_bytes += len(chunk)
    except OSError:
        raise PackagingError("Não foi possível conferir um artefato de saída.") from None
    return ArtifactEvidence(sha256=digest.hexdigest(), size_bytes=size_bytes)


def _member_evidence(archive: zipfile.ZipFile, filename: str) -> ArtifactEvidence:
    digest = hashlib.sha256()
    size_bytes = 0
    with archive.open(filename, "r") as source:
        while chunk := source.read(_CHUNK_SIZE):
            digest.update(chunk)
            size_bytes += len(chunk)
    return ArtifactEvidence(sha256=digest.hexdigest(), size_bytes=size_bytes)


def _ensure_regular_zip_entries(archive: zipfile.ZipFile) -> None:
    for info in archive.infolist():
        file_type = stat.S_IFMT(info.external_attr >> 16)
        if info.is_dir() or file_type not in (0, stat.S_IFREG):
            raise PackagingError("Um ZIP contém uma entrada que não é arquivo regular.")


def _verify_pair_archive(
    path: Path,
    archive_plan: ArchivePlan,
    index: int,
    plan_sha256: str,
    inventory_sha256: str,
) -> ArtifactEvidence:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            _ensure_regular_zip_entries(archive)
            expected_names = [member.member_path for member in archive_plan.members]
            expected_names.append(ARCHIVE_MANIFEST_FILENAME)
            if archive.namelist() != expected_names or archive.testzip() is not None:
                raise PackagingError("Um ZIP de empresa/divisão falhou na verificação.")
            for member in archive_plan.members:
                info = archive.getinfo(member.member_path)
                if info.file_size != member.size_bytes:
                    raise PackagingError("O tamanho de um membro do ZIP não corresponde ao plano.")
                evidence = _member_evidence(archive, member.member_path)
                if evidence.size_bytes != member.size_bytes or evidence.sha256 != member.sha256:
                    raise PackagingError("O conteúdo de um membro do ZIP não corresponde ao plano.")
            actual_manifest = archive.read(ARCHIVE_MANIFEST_FILENAME)
            if actual_manifest != _archive_manifest(
                archive_plan,
                index,
                plan_sha256,
                inventory_sha256,
            ):
                raise PackagingError("O manifest do ZIP não corresponde ao plano.")
    except PackagingError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, KeyError, ValueError):
        raise PackagingError("Um ZIP de empresa/divisão está inválido ou ilegível.") from None
    return _hash_file(path)


def _verify_master_archive(
    path: Path,
    plan: BuildPlan,
    plan_sha256: str,
    inventory_sha256: str,
    archive_evidence: dict[int, ArtifactEvidence],
) -> ArtifactEvidence:
    expected_manifest = _master_manifest(plan, plan_sha256, inventory_sha256, archive_evidence)
    try:
        with zipfile.ZipFile(path, "r") as archive:
            _ensure_regular_zip_entries(archive)
            expected_names = [item.filename for item in plan.archives]
            expected_names.append(MASTER_MANIFEST_FILENAME)
            if archive.namelist() != expected_names or archive.testzip() is not None:
                raise PackagingError("O ZIP mestre falhou na verificação.")
            for index, archive_plan in enumerate(plan.archives):
                info = archive.getinfo(archive_plan.filename)
                expected = archive_evidence[index]
                if info.file_size != expected.size_bytes:
                    raise PackagingError("O tamanho de um pacote no ZIP mestre diverge.")
                actual = _member_evidence(archive, archive_plan.filename)
                if actual != expected:
                    raise PackagingError("O conteúdo de um pacote no ZIP mestre diverge.")
            if archive.read(MASTER_MANIFEST_FILENAME) != expected_manifest:
                raise PackagingError("O manifest do ZIP mestre não corresponde ao plano.")
    except PackagingError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, KeyError, ValueError):
        raise PackagingError("O ZIP mestre está inválido ou ilegível.") from None
    return _hash_file(path)


def _write_pair_archive(
    config: ProjectConfig,
    archive_plan: ArchivePlan,
    index: int,
    plan_sha256: str,
    inventory: Inventory,
) -> ArtifactEvidence:
    temporary, handle = _create_temp_file(archive_plan.output_path.parent, ".trilhadocs-pair-")
    try:
        with handle:
            with zipfile.ZipFile(
                handle,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                strict_timestamps=True,
            ) as archive:
                for member in archive_plan.members:
                    source_path = resolve_source(config.source_root, member.source_path)
                    if PurePosixPath(member.member_path).suffix.casefold() == ".pdf":
                        validate_pdf(source_path)
                    with archive.open(
                        _zip_info(member.member_path), "w", force_zip64=True
                    ) as target:
                        _source_to_zip(source_path, member, target)
                archive.writestr(
                    _zip_info(ARCHIVE_MANIFEST_FILENAME),
                    _archive_manifest(
                        archive_plan,
                        index,
                        plan_sha256,
                        inventory.sha256,
                    ),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                )
            handle.flush()
            os.fsync(handle.fileno())
        _verify_pair_archive(
            temporary,
            archive_plan,
            index,
            plan_sha256,
            inventory.sha256,
        )
        _publish_no_replace(temporary, archive_plan.output_path)
        return _verify_pair_archive(
            archive_plan.output_path,
            archive_plan,
            index,
            plan_sha256,
            inventory.sha256,
        )
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _write_master_archive(
    plan: BuildPlan,
    plan_sha256: str,
    inventory_sha256: str,
    archive_evidence: dict[int, ArtifactEvidence],
    destination: Path,
) -> ArtifactEvidence:
    temporary, handle = _create_temp_file(destination.parent, ".trilhadocs-master-")
    try:
        with handle:
            with zipfile.ZipFile(
                handle,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                strict_timestamps=True,
            ) as master:
                for index, archive_plan in enumerate(plan.archives):
                    expected = archive_evidence[index]
                    with archive_plan.output_path.open("rb") as source:
                        info = _zip_info(archive_plan.filename)
                        with master.open(info, "w", force_zip64=True) as target:
                            digest = hashlib.sha256()
                            size_bytes = 0
                            while chunk := source.read(_CHUNK_SIZE):
                                target.write(chunk)
                                digest.update(chunk)
                                size_bytes += len(chunk)
                    if size_bytes != expected.size_bytes or digest.hexdigest() != expected.sha256:
                        raise PackagingError("Um pacote mudou durante a criação do ZIP mestre.")
                master.writestr(
                    _zip_info(MASTER_MANIFEST_FILENAME),
                    _master_manifest(plan, plan_sha256, inventory_sha256, archive_evidence),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                )
            handle.flush()
            os.fsync(handle.fileno())
        _verify_master_archive(
            temporary,
            plan,
            plan_sha256,
            inventory_sha256,
            archive_evidence,
        )
        _publish_no_replace(temporary, destination)
        return _verify_master_archive(
            destination,
            plan,
            plan_sha256,
            inventory_sha256,
            archive_evidence,
        )
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _summary_bytes(
    plan: BuildPlan,
    plan_sha256: str,
    inventory_sha256: str,
    archive_evidence: dict[int, ArtifactEvidence],
    master_evidence: ArtifactEvidence | None,
) -> bytes:
    output_bytes = sum(item.size_bytes for item in archive_evidence.values())
    if master_evidence is not None:
        output_bytes += master_evidence.size_bytes
    return _canonical_json(
        {
            "schema_version": 1,
            "status": "COMPLETE",
            "plan_sha256": plan_sha256,
            "inventory_sha256": inventory_sha256,
            "master_created": master_evidence is not None,
            "path_limit": plan.path_limit,
            "archive_count": len(plan.archives),
            "member_count": sum(len(archive.members) for archive in plan.archives),
            "output_bytes": output_bytes,
        }
    )


def _write_summary(path: Path, content: bytes) -> None:
    temporary, handle = _create_temp_file(path.parent, ".trilhadocs-summary-")
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _publish_no_replace(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)


def _append_archive_checkpoint(
    journal_path: Path,
    index: int,
    evidence: ArtifactEvidence,
) -> None:
    append_event(
        journal_path,
        {
            "event": "ARCHIVE_VERIFIED",
            "archive_index": index,
            "sha256": evidence.sha256,
            "size_bytes": evidence.size_bytes,
        },
    )


def _validate_resume_state(
    state: JournalState,
    plan: BuildPlan,
    plan_sha256: str,
    inventory: Inventory,
) -> None:
    if (
        state.plan_sha256 != plan_sha256
        or state.inventory_sha256 != inventory.sha256
        or state.archive_count != len(plan.archives)
        or state.master_expected != (plan.master_filename is not None)
    ):
        raise PackagingError("O journal pertence a outro plano ou inventário.")
    expected_member_count = sum(len(archive.members) for archive in plan.archives)
    if state.complete is not None and state.complete["member_count"] != expected_member_count:
        raise PackagingError("A contagem final de membros no journal diverge do plano.")


def _build_job(
    config: ProjectConfig, inventory: Inventory, plan: BuildPlan, resume: bool
) -> BuildResult:
    validate_inventory(inventory)
    if (
        not isinstance(inventory.sha256, str)
        or len(inventory.sha256) != 64
        or any(char not in "0123456789abcdef" for char in inventory.sha256)
    ):
        raise PackagingError("O hash do inventário é inválido.")
    expected_plan = build_member_plan(config, inventory)
    if expected_plan != plan:
        raise PackagingError("O plano recebido não corresponde à configuração e ao inventário.")

    output_dir = plan.output_dir
    if output_dir.exists() and not output_dir.is_dir():
        raise PackagingError("O destino de saída não é uma pasta.")
    journal_path = output_dir / JOURNAL_FILENAME
    summary_path = output_dir / SUMMARY_FILENAME
    plan_sha256 = _plan_digest(plan, inventory)
    archive_evidence: dict[int, ArtifactEvidence] = {}
    master_evidence: ArtifactEvidence | None = None

    if resume:
        if not output_dir.is_dir() or journal_path.is_symlink() or not journal_path.is_file():
            raise PackagingError("Não há um journal retomável neste destino.")
        state = read_journal(journal_path)
        _validate_resume_state(state, plan, plan_sha256, inventory)

        for index, archive_plan in enumerate(plan.archives):
            recorded = state.archives.get(index)
            if archive_plan.output_path.is_symlink():
                raise PackagingError("Um ZIP de empresa/divisão não pode ser link simbólico.")
            if not archive_plan.output_path.exists():
                if recorded is not None:
                    raise PackagingError("Um ZIP registrado no journal está ausente.")
                continue
            actual = _verify_pair_archive(
                archive_plan.output_path,
                archive_plan,
                index,
                plan_sha256,
                inventory.sha256,
            )
            if recorded is not None and (
                recorded["sha256"] != actual.sha256 or recorded["size_bytes"] != actual.size_bytes
            ):
                raise PackagingError("Um ZIP existente diverge do checkpoint registrado.")
            archive_evidence[index] = actual
            if recorded is None:
                _append_archive_checkpoint(journal_path, index, actual)
                state = read_journal(journal_path)

        master_path = output_dir / plan.master_filename if plan.master_filename else None
        if master_path is not None and master_path.is_symlink():
            raise PackagingError("O ZIP mestre não pode ser link simbólico.")
        if master_path is not None and master_path.exists():
            if len(archive_evidence) != len(plan.archives):
                raise PackagingError("O ZIP mestre existe sem todos os ZIPs verificados.")
            master_evidence = _verify_master_archive(
                master_path,
                plan,
                plan_sha256,
                inventory.sha256,
                archive_evidence,
            )
            if state.master is not None and (
                state.master["sha256"] != master_evidence.sha256
                or state.master["size_bytes"] != master_evidence.size_bytes
            ):
                raise PackagingError("O ZIP mestre diverge do checkpoint registrado.")
            if state.master is None:
                append_event(
                    journal_path,
                    {
                        "event": "MASTER_VERIFIED",
                        "sha256": master_evidence.sha256,
                        "size_bytes": master_evidence.size_bytes,
                    },
                )
                state = read_journal(journal_path)
        elif state.master is not None:
            raise PackagingError("O ZIP mestre registrado no journal está ausente.")

        if state.complete is not None:
            expected_summary = _summary_bytes(
                plan,
                plan_sha256,
                inventory.sha256,
                archive_evidence,
                master_evidence,
            )
            if not summary_path.is_file() or summary_path.read_bytes() != expected_summary:
                raise PackagingError("O resumo COMPLETE não corresponde ao resultado verificado.")
            summary_digest = hashlib.sha256(expected_summary).hexdigest()
            if state.complete["summary_sha256"] != summary_digest:
                raise PackagingError("O resumo COMPLETE diverge do checkpoint registrado.")
            output_bytes = sum(item.size_bytes for item in archive_evidence.values())
            if master_evidence is not None:
                output_bytes += master_evidence.size_bytes
            return BuildResult(
                complete=True,
                archive_count=len(plan.archives),
                member_count=sum(len(archive.members) for archive in plan.archives),
                output_bytes=output_bytes,
                plan_sha256=plan_sha256,
            )

        if summary_path.exists():
            if len(archive_evidence) != len(plan.archives) or (
                plan.master_filename is not None and master_evidence is None
            ):
                raise PackagingError("Existe um resumo de saída antes da verificação completa.")
            expected_summary = _summary_bytes(
                plan,
                plan_sha256,
                inventory.sha256,
                archive_evidence,
                master_evidence,
            )
            if summary_path.read_bytes() != expected_summary:
                raise PackagingError("Existe um resumo COMPLETE que não corresponde aos artefatos.")

        reserved_bytes = sum(item.size_bytes for item in archive_evidence.values())
        if master_evidence is not None:
            reserved_bytes += master_evidence.size_bytes
        required_remaining = max(0, plan.required_bytes - reserved_bytes)
        if _available_bytes(output_dir) < required_remaining:
            raise PackagingError("Espaço livre insuficiente para continuar o build.")
    else:
        _ensure_no_fresh_conflicts(plan)
        free_bytes = _available_bytes(output_dir)
        try:
            preflight(plan, free_bytes)
        except PreflightError as error:
            raise PackagingError(str(error)) from None
        output_dir.mkdir(parents=True, exist_ok=True)
        create_journal(
            journal_path,
            plan_sha256=plan_sha256,
            inventory_sha256=inventory.sha256,
            archive_count=len(plan.archives),
            master_expected=plan.master_filename is not None,
        )
        _sync_directory(output_dir)
        state = read_journal(journal_path)

    for index, archive_plan in enumerate(plan.archives):
        if index in archive_evidence:
            continue
        evidence = _write_pair_archive(config, archive_plan, index, plan_sha256, inventory)
        archive_evidence[index] = evidence
        _append_archive_checkpoint(journal_path, index, evidence)
        state = read_journal(journal_path)

    if plan.master_filename is not None and master_evidence is None:
        master_path = output_dir / plan.master_filename
        master_evidence = _write_master_archive(
            plan,
            plan_sha256,
            inventory.sha256,
            archive_evidence,
            master_path,
        )
        append_event(
            journal_path,
            {
                "event": "MASTER_VERIFIED",
                "sha256": master_evidence.sha256,
                "size_bytes": master_evidence.size_bytes,
            },
        )
        state = read_journal(journal_path)

    for index, archive_plan in enumerate(plan.archives):
        final_evidence = _verify_pair_archive(
            archive_plan.output_path,
            archive_plan,
            index,
            plan_sha256,
            inventory.sha256,
        )
        if final_evidence != archive_evidence.get(index):
            raise PackagingError("Um ZIP mudou antes da finalização do build.")
        archive_evidence[index] = final_evidence

    if plan.master_filename is not None:
        final_master = _verify_master_archive(
            output_dir / plan.master_filename,
            plan,
            plan_sha256,
            inventory.sha256,
            archive_evidence,
        )
        if final_master != master_evidence:
            raise PackagingError("O ZIP mestre mudou antes da finalização do build.")
        master_evidence = final_master

    summary_content = _summary_bytes(
        plan,
        plan_sha256,
        inventory.sha256,
        archive_evidence,
        master_evidence,
    )
    if summary_path.exists():
        if summary_path.read_bytes() != summary_content:
            raise PackagingError("Existe um resumo de saída que não corresponde ao build.")
    else:
        _write_summary(summary_path, summary_content)
    summary_sha256 = hashlib.sha256(summary_content).hexdigest()
    append_event(
        journal_path,
        {
            "event": "COMPLETE",
            "summary_sha256": summary_sha256,
            "archive_count": len(plan.archives),
            "member_count": sum(len(archive.members) for archive in plan.archives),
        },
    )
    state = read_journal(journal_path)
    if state.complete is None:
        raise PackagingError("O journal não confirmou a conclusão do build.")

    output_bytes = sum(item.size_bytes for item in archive_evidence.values())
    if master_evidence is not None:
        output_bytes += master_evidence.size_bytes
    return BuildResult(
        complete=True,
        archive_count=len(plan.archives),
        member_count=sum(len(archive.members) for archive in plan.archives),
        output_bytes=output_bytes,
        plan_sha256=plan_sha256,
    )


def build_job(
    config: ProjectConfig,
    inventory: Inventory,
    plan: BuildPlan,
    resume: bool = False,
) -> BuildResult:
    """Build deterministic per-pair ZIPs and optionally resume verified checkpoints."""
    try:
        return _build_job(config, inventory, plan, resume)
    except PackagingError:
        raise
    except Exception as error:
        # Keep local paths, account labels and raw parser details out of audit output.
        if isinstance(error, PreflightError):
            raise PackagingError(str(error)) from None
        raise PackagingError(
            "O build falhou; as fontes foram preservadas e o journal pode ser retomado."
        ) from None
