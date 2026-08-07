"""Tests for PropertySheet.commit numeric row validation.

Numeric rows must accept only values matching their declared kind:
"int" rows reject booleans (a ``bool`` is an ``int`` subclass) and
fractional values, "float" rows reject non-numeric values, and
rejected values are dropped before assignment and notification.
"""

from __future__ import annotations

from typing import Any

from projectionai.ui.viewmodels.properties import PropertySheet


def _sheet() -> tuple[PropertySheet, list[tuple[str, Any]]]:
    sheet = PropertySheet()
    section = sheet.add_section("Test")
    sheet.add_int(section, "age", "Age", value=30, minimum=0, maximum=100)
    sheet.add_float(section, "ratio", "Ratio", value=0.5, minimum=0.0, maximum=1.0)
    sheet.add_text(section, "name", "Name", value="Ada")
    changes: list[tuple[str, Any]] = []
    sheet.on_changed(lambda row_id, value: changes.append((row_id, value)))
    return sheet, changes


def _value(sheet: PropertySheet, row_id: str) -> Any:
    row = sheet.row(row_id)
    assert row is not None
    return row.value


class TestIntRowValidation:
    def test_accepts_int(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("age", 42)
        assert _value(sheet, "age") == 42
        assert changes == [("age", 42)]

    def test_rejects_bool(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("age", True)
        assert _value(sheet, "age") == 30
        assert changes == []

    def test_rejects_fractional_float(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("age", 30.5)
        assert _value(sheet, "age") == 30
        assert changes == []

    def test_rejects_infinity_without_overflow(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("age", float("inf"))
        assert _value(sheet, "age") == 30
        assert changes == []

    def test_rejects_nan_without_error(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("age", float("nan"))
        assert _value(sheet, "age") == 30
        assert changes == []

    def test_rejects_string(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("age", "thirty")
        assert _value(sheet, "age") == 30
        assert changes == []

    def test_clamps_bounds(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("age", 1000)
        assert _value(sheet, "age") == 100
        assert changes == [("age", 100)]

    def test_accepts_oversized_int_without_overflow(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("age", 10**100)
        assert _value(sheet, "age") == 100
        assert changes == [("age", 100)]


class TestFloatRowValidation:
    def test_accepts_float_and_int(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("ratio", 0.75)
        assert _value(sheet, "ratio") == 0.75
        sheet.commit("ratio", 1)
        assert _value(sheet, "ratio") == 1
        assert changes == [("ratio", 0.75), ("ratio", 1)]

    def test_rejects_bool(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("ratio", True)
        assert _value(sheet, "ratio") == 0.5
        assert changes == []

    def test_rejects_string(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("ratio", "half")
        assert _value(sheet, "ratio") == 0.5
        assert changes == []

    def test_rejects_infinity(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("ratio", float("inf"))
        assert _value(sheet, "ratio") == 0.5
        assert changes == []

    def test_rejects_nan(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("ratio", float("nan"))
        assert _value(sheet, "ratio") == 0.5
        assert changes == []

    def test_clamps_bounds(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("ratio", 5.0)
        assert _value(sheet, "ratio") == 1.0
        assert changes == [("ratio", 1.0)]

    def test_accepts_oversized_int_without_overflow(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("ratio", 10**100)
        assert _value(sheet, "ratio") == 1.0
        assert changes == [("ratio", 1.0)]


class TestNonNumericRows:
    def test_text_rows_unchanged(self) -> None:
        sheet, changes = _sheet()
        sheet.commit("name", 123)
        assert _value(sheet, "name") == 123
        assert changes == [("name", 123)]
