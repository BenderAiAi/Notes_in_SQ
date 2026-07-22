from datetime import date
from pathlib import Path

import pytest

from notes_app.terminations.service import eligible_excel_files, scan_reports


def test_scan_selects_latest_by_termination_date(temp_data, make_report):
    source = temp_data / "reports"
    source.mkdir()
    make_report(source / "a.xlsx", contract="F1", term_date="10.07.2026")
    make_report(source / "b.xlsx", contract="F2", term_date="17.07.2026")

    result = scan_reports(source)

    assert result["latest_termination_date"] == "2026-07-17"
    assert [item["file_name"] for item in result["candidates"]] == ["b.xlsx"]
    assert result["stats"]["found"] == 2


def test_scan_ignores_output_files(temp_data, make_report):
    source = temp_data / "reports"
    source.mkdir()
    make_report(source / "source.xlsx", contract="F1")
    make_report(source / "17-07-2026-Dubai_term.xlsx", contract="F9")

    files = eligible_excel_files(source)

    assert [path.name for path in files] == ["source.xlsx"]


def test_unrecognized_file_is_separated(temp_data, tmp_path):
    from openpyxl import Workbook

    source = temp_data / "reports"
    source.mkdir()
    workbook = Workbook()
    workbook.active.append(["foo", "bar", "baz"])
    workbook.save(source / "not_a_report.xlsx")

    result = scan_reports(source)

    assert result["latest_termination_date"] is None
    assert len(result["unrecognized"]) == 1
    assert "error" in result["unrecognized"][0]


def test_is_today_flag(temp_data, make_report):
    source = temp_data / "reports"
    source.mkdir()
    today = date.today()
    make_report(source / "today.xlsx", term_date=today.strftime("%d.%m.%Y"))

    result = scan_reports(source)

    assert result["is_today"] is True
    assert result["latest_termination_date"] == today.isoformat()


def test_second_scan_uses_index(temp_data, make_report):
    source = temp_data / "reports"
    source.mkdir()
    make_report(source / "a.xlsx", contract="F1", term_date="17.07.2026")

    first = scan_reports(source)
    second = scan_reports(source)

    assert first["stats"]["read"] == 1
    assert second["stats"]["from_index"] == 1
    assert second["stats"]["read"] == 0
