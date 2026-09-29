from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from trilhadocs.config import load_config
from trilhadocs.inventory import load_inventory
from trilhadocs.models import AccountRecord, AttachmentRecord, FileRef

_SYNTHETIC_DOCUMENTS = {
    "covers/demo-cover-alpha.pdf": "Synthetic cover for demo account alpha",
    "attachments/demo-evidence-alpha.pdf": "Synthetic evidence for demo account alpha",
    "attachments/demo-evidence-beta.pdf": "Synthetic evidence for demo account beta",
}


def _synthetic_pdf_bytes(label: str) -> bytes:
    """Build a small deterministic one-page PDF from an invented label."""
    if not label.isascii() or any(character in label for character in "\\()\r\n"):
        raise ValueError("Rótulo sintético de PDF inválido.")

    content = f"BT /F1 10 Tf 36 36 Td ({label}) Tj ET".encode("ascii")
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )

    parts = [b"%PDF-1.4\n"]
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(sum(map(len, parts)))
        parts.extend(
            (
                f"{object_number} 0 obj\n".encode("ascii"),
                body,
                b"\nendobj\n",
            )
        )

    xref_offset = sum(map(len, parts))
    parts.append(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    parts.extend(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
    parts.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return b"".join(parts)


def _file_references(
    accounts: tuple[AccountRecord, ...], attachments: tuple[AttachmentRecord, ...]
) -> tuple[FileRef, ...]:
    covers = tuple(account.cover for account in accounts if account.cover is not None)
    return (*covers, *attachments)


def _write_if_missing(path: Path, content: bytes) -> None:
    if path.exists():
        if path.is_file() and path.read_bytes() == content:
            return
        raise FileExistsError("O destino contém um arquivo diferente.")

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as output:
            output.write(content)
    except FileExistsError:
        if path.is_file() and path.read_bytes() == content:
            return
        raise FileExistsError("O destino contém um arquivo diferente.") from None


def create_demo(destination: Path) -> Path:
    """Copy the public templates and generate their synthetic PDFs outside the repo."""
    template_root = Path(__file__).resolve().parent
    project_root = template_root.parents[1]
    target_root = Path(destination).expanduser().resolve(strict=False)
    if target_root.is_relative_to(project_root):
        raise ValueError("O destino da demo deve ficar fora do repositório.")

    config_template = template_root / "config.toml"
    inventory_template = template_root / "inventory.jsonl"
    config = load_config(config_template)
    inventory = load_inventory(inventory_template)

    generated_documents: dict[str, bytes] = {}
    for file_ref in _file_references(tuple(inventory.accounts.values()), inventory.attachments):
        label = _SYNTHETIC_DOCUMENTS.get(file_ref.source_path)
        if label is None or file_ref.source_path in generated_documents:
            raise ValueError("O inventário do demo não corresponde às fontes sintéticas.")
        document = _synthetic_pdf_bytes(label)
        digest = hashlib.sha256(document).hexdigest()
        if len(document) != file_ref.size_bytes or digest != file_ref.sha256:
            raise ValueError("O inventário do demo não corresponde às fontes sintéticas.")
        generated_documents[file_ref.source_path] = document

    if generated_documents.keys() != _SYNTHETIC_DOCUMENTS.keys():
        raise ValueError("O inventário do demo não corresponde às fontes sintéticas.")

    source_root = target_root / config.source_root.relative_to(template_root)
    writes = {
        target_root / "config.toml": config_template.read_bytes(),
        target_root / "inventory.jsonl": inventory_template.read_bytes(),
        **{
            source_root / Path(*relative_path.split("/")): document
            for relative_path, document in generated_documents.items()
        },
    }
    resolved_writes: dict[Path, bytes] = {}
    for path, content in writes.items():
        resolved_path = path.resolve(strict=False)
        if not resolved_path.is_relative_to(target_root):
            raise ValueError("O destino contém um caminho que sai da pasta da demo.")
        resolved_writes[resolved_path] = content

    resolved_source_root = source_root.resolve(strict=False)
    if not resolved_source_root.is_relative_to(target_root):
        raise ValueError("O destino contém um caminho que sai da pasta da demo.")

    directories = {target_root, resolved_source_root}
    directories.update(
        path.parent for path in resolved_writes if path != target_root / "config.toml"
    )
    for directory in directories:
        if directory.exists() and not directory.is_dir():
            raise FileExistsError("O destino contém um arquivo no lugar de uma pasta.")
    for path, content in resolved_writes.items():
        if path.exists() and (not path.is_file() or path.read_bytes() != content):
            raise FileExistsError("O destino contém um arquivo diferente.")

    for path, content in resolved_writes.items():
        _write_if_missing(path, content)

    return target_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera uma demo TrilhaDocs com dados e PDFs inteiramente sintéticos."
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="pasta fora do repositório onde config, inventário e fontes serão gerados",
    )
    args = parser.parse_args()
    try:
        create_demo(args.destination)
    except (OSError, ValueError):
        parser.error("Não foi possível gerar a demo no destino solicitado.")
    print("Demo sintético criado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
