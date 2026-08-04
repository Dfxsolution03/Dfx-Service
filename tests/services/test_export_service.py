"""
JROS Service Tests — Export Service (Module 15)
================================================

Pure unit tests, no DB — ExportService is domain-agnostic (rows + columns in,
file bytes out), so it's tested in isolation from any repository/service.
"""

import base64
import csv
import io

import pytest
from openpyxl import load_workbook

from app.services.export_service import ExportService, ExportColumn

COLUMNS = [ExportColumn("name", "Name"), ExportColumn("amount", "Amount")]
ROWS = [
    {"name": "Alpha", "amount": 100},
    {"name": "Beta | Pipe", "amount": 250.5},
]


class TestCsvExport:
    def test_generates_correct_headers_and_rows(self):
        result = ExportService.generate(ROWS, COLUMNS, "csv", "test_export")
        raw = base64.b64decode(result.content_base64).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(raw)))
        assert rows[0] == ["Name", "Amount"]
        assert rows[1] == ["Alpha", "100"]
        assert rows[2] == ["Beta | Pipe", "250.5"]

    def test_metadata_is_correct(self):
        result = ExportService.generate(ROWS, COLUMNS, "csv", "test_export")
        assert result.filename == "test_export.csv"
        assert result.content_type == "text/csv"
        assert result.format == "csv"
        assert result.row_count == 2


class TestExcelExport:
    def test_generates_correct_headers_and_rows(self):
        result = ExportService.generate(ROWS, COLUMNS, "excel", "test_export")
        raw = base64.b64decode(result.content_base64)
        wb = load_workbook(io.BytesIO(raw))
        ws = wb.active
        values = list(ws.values)
        assert values[0] == ("Name", "Amount")
        assert values[1] == ("Alpha", 100)
        assert values[2] == ("Beta | Pipe", 250.5)

    def test_metadata_is_correct(self):
        result = ExportService.generate(ROWS, COLUMNS, "excel", "test_export")
        assert result.filename == "test_export.xlsx"
        assert result.content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert result.row_count == 2


class TestMarkdownExport:
    def test_generates_correct_table(self):
        result = ExportService.generate(ROWS, COLUMNS, "markdown", "test_export")
        raw = base64.b64decode(result.content_base64).decode("utf-8")
        lines = raw.strip().split("\n")
        assert lines[0] == "| Name | Amount |"
        assert lines[1] == "| --- | --- |"
        assert lines[2] == "| Alpha | 100 |"

    def test_escapes_pipe_characters_in_cell_values(self):
        result = ExportService.generate(ROWS, COLUMNS, "markdown", "test_export")
        raw = base64.b64decode(result.content_base64).decode("utf-8")
        assert "Beta \\| Pipe" in raw

    def test_metadata_is_correct(self):
        result = ExportService.generate(ROWS, COLUMNS, "markdown", "test_export")
        assert result.filename == "test_export.md"
        assert result.content_type == "text/markdown"


class TestEmptyRows:
    @pytest.mark.parametrize("fmt", ["csv", "excel", "markdown"])
    def test_produces_header_only_file(self, fmt):
        result = ExportService.generate([], COLUMNS, fmt, "empty_export")
        assert result.row_count == 0
        assert result.content_base64  # still a valid, non-empty file


class TestUnsupportedFormat:
    def test_raises_value_error(self):
        with pytest.raises(ValueError):
            ExportService.generate(ROWS, COLUMNS, "pdf", "test_export")  # type: ignore[arg-type]
