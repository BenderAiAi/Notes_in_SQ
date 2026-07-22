import pandas as pd
import pytest
from openpyxl import Workbook

from notes_app.terminations.excel_ingest import (
    DISSOLUTION_MANUAL,
    DISSOLUTION_MSSP,
    read_and_clean_excel,
)


FULL_HEADERS = [
    "Status",
    "Date of early termination",
    "Contract number",
    "Notional amount",
    "CUR of notional amount",
    "Quote",
    "Invested amount",
    "CUR of invested amount",
    "Early termination amount",
    "CUR of early termination amount",
]


def _write_excel(path, rows, headers=FULL_HEADERS):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    workbook.save(path)


def test_reads_new_format_and_parses_russian_numbers(tmp_path):
    path = tmp_path / "term.xlsx"
    _write_excel(
        path,
        [
            ["Uploaded WEB", "17.07.2026", "F6123312321320", "15 000 000,00", "CNY", "1,0115", "15000,00", "CNY", "15500,00", "CNY"],
            ["Created", "17.07.2026", "F6012312332112300023", "30 000 000,00", "CNY", "1,0115", "3000,00", "CNY", "3 000,00", "CNY"],
        ],
    )

    clean, report = read_and_clean_excel(str(path))

    assert list(clean["contract_number"]) == ["F6123312321320", "F6012312332112300023"]
    assert list(clean["termination_amount"]) == [15500.0, 3000.0]
    assert list(clean["notional_amount"]) == [15000000.0, 30000000.0]
    assert list(clean["currency"]) == ["CNY", "CNY"]
    assert list(clean["quote"]) == [1.0115, 1.0115]
    assert list(clean["dissolution_type"]) == [DISSOLUTION_MSSP, DISSOLUTION_MANUAL]
    assert report.input_rows == 2
    assert report.output_rows == 2
    assert str(report.latest_termination_date) == "2026-07-17"


def test_header_can_be_below_junk_rows(tmp_path):
    path = tmp_path / "junk.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Отчёт по расторжениям на дату", None, None])
    worksheet.append([None, None, None])
    worksheet.append(FULL_HEADERS)
    worksheet.append(
        ["Created", "01.02.2026", "F1", "1 000 000,00", "USD", "1,0", "1000", "USD", "2500,00", "USD"]
    )
    workbook.save(path)

    clean, report = read_and_clean_excel(str(path))

    assert list(clean["contract_number"]) == ["F1"]
    assert list(clean["termination_amount"]) == [2500.0]
    assert report.output_rows == 1


def test_incomplete_rows_are_ignored_and_reported(tmp_path):
    path = tmp_path / "incomplete.xlsx"
    _write_excel(
        path,
        [
            ["Created", "17.07.2026", "F1", "1 000 000,00", "USD", "1,0", "1000", "USD", "1000,00", "USD"],
            ["Created", "17.07.2026", "F2", "2 000 000,00", "USD", "1,0", "2000", "USD", "", "USD"],
        ],
    )

    clean, report = read_and_clean_excel(str(path))

    assert list(clean["contract_number"]) == ["F1"]
    assert report.input_rows == 2
    assert report.output_rows == 1
    assert report.ignored_incomplete_rows == 1
    assert report.incomplete_row_examples == ["F2"]


def test_duplicate_contract_keeps_first(tmp_path):
    path = tmp_path / "dupes.xlsx"
    _write_excel(
        path,
        [
            ["Created", "17.07.2026", "F1", "1 000 000,00", "USD", "1,0", "1000", "USD", "1000,00", "USD"],
            ["Uploaded WEB", "17.07.2026", "F1", "1 000 000,00", "AED", "1,0", "1000", "USD", "2000,00", "AED"],
            ["Created", "17.07.2026", "F2", "2 000 000,00", "USD", "1,0", "2000", "USD", "2000,00", "USD"],
        ],
    )

    clean, report = read_and_clean_excel(str(path))

    assert list(clean["contract_number"]) == ["F1", "F2"]
    assert report.dropped_duplicates == 1
    assert any("F1" in warning for warning in report.duplicate_warnings)


def test_missing_required_column_raises(tmp_path):
    path = tmp_path / "missing.xlsx"
    _write_excel(
        path,
        [["Created", "17.07.2026", "F1", "1000,00", "USD"]],
        headers=[
            "Status",
            "Date of early termination",
            "Contract number",
            "Early termination amount",
            "CUR of early termination amount",
        ],
    )

    with pytest.raises(ValueError, match="notional_amount"):
        read_and_clean_excel(str(path))
