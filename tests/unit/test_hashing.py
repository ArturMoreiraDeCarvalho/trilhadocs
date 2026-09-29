import hashlib
from pathlib import Path

import pytest

from trilhadocs.hashing import ContentMismatchError, inspect_file


def test_inspect_file_streams_and_returns_actual_size_and_sha256(tmp_path: Path) -> None:
    source = tmp_path / "synthetic-large-file.bin"
    content = b"synthetic-block-" * 150_000
    source.write_bytes(content)
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    evidence = inspect_file(source, len(content), hashlib.sha256(content).hexdigest().upper())

    assert evidence.size_bytes == len(content)
    assert evidence.sha256 == before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("mismatch", ["size", "sha256"])
def test_inspect_file_rejects_expected_content_mismatch_without_mutating_source(
    tmp_path: Path, mismatch: str
) -> None:
    source = tmp_path / "synthetic-document.bin"
    content = b"synthetic accounting attachment"
    source.write_bytes(content)
    original_hash = hashlib.sha256(content).hexdigest()
    expected_size = len(content) + (1 if mismatch == "size" else 0)
    expected_hash = "0" * 64 if mismatch == "sha256" else original_hash

    with pytest.raises(ContentMismatchError) as error:
        inspect_file(source, expected_size, expected_hash)

    assert str(source) not in str(error.value)
    assert source.read_bytes() == content


def test_inspect_file_rejects_invalid_digest_argument_safely(tmp_path: Path) -> None:
    source = tmp_path / "synthetic-document.bin"
    source.write_bytes(b"synthetic")

    with pytest.raises(ContentMismatchError):
        inspect_file(source, 9, "invalid")
