from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

import typer

from trilhadocs.config import ConfigurationError, ProjectConfig, load_config
from trilhadocs.hashing import ContentMismatchError, inspect_file
from trilhadocs.inventory import Inventory, InventoryError, load_inventory
from trilhadocs.models import FileRef
from trilhadocs.packaging import BuildResult, PackagingError, build_job
from trilhadocs.paths import SourcePathError, resolve_source
from trilhadocs.pdf_validation import PdfValidationError, validate_pdf
from trilhadocs.planning import (
    BuildPlan,
    PlanningError,
    PreflightError,
    build_member_plan,
    preflight,
)
from trilhadocs.verification import VerificationResult, verify_job

app = typer.Typer(
    add_completion=False, no_args_is_help=True, help="CLI local para pacotes auditáveis."
)


def _emit_json(value: dict[str, object]) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _fail(code: int, status: str, message: str) -> None:
    _emit_json({"status": status, "error": message})
    raise typer.Exit(code=code)


def _load_inputs(config_path: Path) -> tuple[ProjectConfig, Inventory]:
    try:
        config = load_config(config_path)
        inventory = load_inventory(config.inventory_path)
        return config, inventory
    except (ConfigurationError, InventoryError):
        _fail(2, "INVALID_INPUT", "Configuração ou inventário inválido.")


def _free_bytes(path: Path) -> int:
    candidate = Path(path)
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise PreflightError("Não foi possível verificar o espaço local.")
        candidate = parent
    if not candidate.is_dir():
        candidate = candidate.parent
    try:
        return shutil.disk_usage(candidate).free
    except OSError:
        raise PreflightError("Não foi possível verificar o espaço local.") from None


def _plan(config: ProjectConfig, inventory: Inventory) -> BuildPlan:
    try:
        return build_member_plan(config, inventory)
    except PlanningError:
        _fail(2, "INVALID_INPUT", "Não foi possível formar o plano do inventário.")


def _run_preflight(plan: BuildPlan) -> None:
    if plan.output_dir.exists() and not plan.output_dir.is_dir():
        raise PreflightError("O destino de saída não é uma pasta.")
    preflight(plan, _free_bytes(plan.output_dir))


def _validate_sources(config: ProjectConfig, inventory: Inventory, plan: BuildPlan) -> None:
    pdf_sources = {
        member.source_path
        for archive in plan.archives
        for member in archive.members
        if PurePosixPath(member.member_path).suffix.casefold() == ".pdf"
    }
    files = [account.cover for account in inventory.accounts.values() if account.cover]
    files.extend(inventory.attachments)

    def inspect_source(file_ref: FileRef) -> None:
        source = resolve_source(config.source_root, file_ref.source_path)
        inspect_file(source, file_ref.size_bytes, file_ref.sha256)
        if file_ref.source_path in pdf_sources:
            validate_pdf(source)

    try:
        with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
            for batch_start in range(0, len(files), config.max_workers):
                batch = files[batch_start : batch_start + config.max_workers]
                futures = [executor.submit(inspect_source, file_ref) for file_ref in batch]
                for future in futures:
                    future.result()
    except (SourcePathError, ContentMismatchError, PdfValidationError):
        _fail(3, "INTEGRITY_FAILURE", "Uma fonte não passou na conferência de conteúdo.")


def _plan_summary(plan: BuildPlan) -> tuple[int, int, int, int]:
    archives = plan.archives
    return (
        len(archives),
        sum(len(archive.members) for archive in archives),
        plan.required_bytes,
        plan.max_path_chars,
    )


@app.command()
def validate(
    config_path: Path = typer.Option(..., "--config"),  # noqa: B008
) -> None:
    """Validate the inventory and every referenced local document without writing output."""
    config, inventory = _load_inputs(config_path)
    plan = _plan(config, inventory)
    try:
        _run_preflight(plan)
    except PreflightError:
        _fail(3, "PREFLIGHT_FAILURE", "O preflight de saída falhou.")
    _validate_sources(config, inventory, plan)
    archive_count, member_count, required_bytes, max_path_chars = _plan_summary(plan)
    _emit_json(
        {
            "status": "VALID",
            "archive_count": archive_count,
            "member_count": member_count,
            "required_bytes": required_bytes,
            "max_path_chars": max_path_chars,
        }
    )


@app.command()
def preview(
    config_path: Path = typer.Option(..., "--config"),  # noqa: B008
) -> None:
    """Show a redacted plan and disk estimate without reading or writing documents."""
    config, inventory = _load_inputs(config_path)
    plan = _plan(config, inventory)
    try:
        _run_preflight(plan)
    except PreflightError:
        _fail(3, "PREFLIGHT_FAILURE", "O preflight de saída falhou.")
    archive_count, member_count, required_bytes, max_path_chars = _plan_summary(plan)
    _emit_json(
        {
            "status": "READY",
            "archive_count": archive_count,
            "member_count": member_count,
            "required_bytes": required_bytes,
            "max_path_chars": max_path_chars,
        }
    )


@app.command()
def build(
    config_path: Path = typer.Option(..., "--config"),  # noqa: B008
    resume: bool = typer.Option(False, "--resume", help="Retoma checkpoints verificados."),
) -> None:
    """Create verified per-pair ZIPs, an optional master, manifests and a journal."""
    config, inventory = _load_inputs(config_path)
    plan = _plan(config, inventory)
    try:
        result = build_job(config, inventory, plan, resume=resume)
    except PackagingError:
        _fail(3, "BUILD_FAILURE", "O build falhou; confira o destino e os checkpoints locais.")
    _emit_json(_build_result(result))
    if not result.complete:
        raise typer.Exit(code=3)


@app.command()
def verify(
    config_path: Path = typer.Option(..., "--config"),  # noqa: B008
) -> None:
    """Independently reopen the output ZIPs and compare them to the inventory."""
    config, inventory = _load_inputs(config_path)
    result = verify_job(config.output_dir, inventory)
    _emit_json(_verification_result(result))
    if not result.valid:
        raise typer.Exit(code=3)


def _build_result(result: BuildResult) -> dict[str, object]:
    return {
        "status": "COMPLETE" if result.complete else "PARTIAL",
        "archive_count": result.archive_count,
        "member_count": result.member_count,
        "output_bytes": result.output_bytes,
    }


def _verification_result(result: VerificationResult) -> dict[str, object]:
    return {
        "valid": result.valid,
        "archive_count": result.archive_count,
        "member_count": result.member_count,
        "output_bytes": result.output_bytes,
        "issues": list(result.issues),
    }
