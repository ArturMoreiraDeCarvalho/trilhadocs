import pytest

from trilhadocs.paths import safe_windows_component


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("CON", "_CON"),
        ("aux.txt", "_aux.txt"),
        ("Lpt9.", "_Lpt9"),
        ("COM10", "COM10"),
        ("  account name.  ", "account name"),
        ("Alpha?Beta", "Alpha_Beta"),
        ("Cafe\u0301", "Café"),
        ("...   ", "_"),
    ],
)
def test_safe_windows_component_sanitizes_names(value: str, expected: str) -> None:
    assert safe_windows_component(value) == expected


def test_safe_windows_component_rejects_non_string_input() -> None:
    with pytest.raises(ValueError):
        safe_windows_component(123)  # type: ignore[arg-type]
