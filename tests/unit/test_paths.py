from pathlib import Path

import pytest

from trilhadocs.paths import SourcePathError, resolve_source


def test_resolve_source_accepts_a_file_confined_to_root(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    source = root / "nested" / "document.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"synthetic")

    assert resolve_source(root, "nested/document.pdf") == source.resolve(strict=True)


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.pdf",
        "nested/../../outside.pdf",
        "/etc/passwd",
        "C:/private/file.pdf",
        "C:private.pdf",
        "\\\\server\\share\\file.pdf",
        "nested\\..\\outside.pdf",
        "nested\\document.pdf",
        "",
        ".",
    ],
)
def test_resolve_source_rejects_absolute_or_noncanonical_paths(
    tmp_path: Path, relative_path: str
) -> None:
    root = tmp_path / "sources"
    root.mkdir()

    with pytest.raises(SourcePathError) as error:
        resolve_source(root, relative_path)

    if relative_path not in {"", "."}:
        assert relative_path not in str(error.value)


def test_resolve_source_rejects_missing_files_and_directories(tmp_path: Path) -> None:
    root = tmp_path / "sources"
    root.mkdir()
    (root / "folder").mkdir()

    for relative_path in ("missing.pdf", "folder"):
        with pytest.raises(SourcePathError):
            resolve_source(root, relative_path)


def test_resolve_source_rejects_symlink_that_resolves_outside_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sources"
    root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"private synthetic fixture")
    link = root / "escape.pdf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        original_resolve = Path.resolve

        def resolve_with_external_link(self: Path, strict: bool = False) -> Path:
            if self == link:
                return outside.resolve(strict=True)
            return original_resolve(self, strict=strict)

        monkeypatch.setattr(Path, "resolve", resolve_with_external_link)

    with pytest.raises(SourcePathError) as error:
        resolve_source(root, "escape.pdf")

    assert str(outside) not in str(error.value)
    assert outside.read_bytes() == b"private synthetic fixture"


def test_resolve_source_rejects_missing_root_without_echoing_path(tmp_path: Path) -> None:
    root = tmp_path / "private-root"

    with pytest.raises(SourcePathError) as error:
        resolve_source(root, "document.pdf")

    assert str(root) not in str(error.value)
