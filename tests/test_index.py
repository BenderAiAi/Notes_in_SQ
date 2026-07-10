from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

import notes_app.database as database
from notes_app.excel import SOURCE_HEADERS
from notes_app.service import scan_reports


def make_minimal_source(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(SOURCE_HEADERS)
    sheet.append([1, "10.07.2026", "13.07.2026", "10:37:14", "XS1", "Купля", "41,01", 35, 100, "SUR", "USD", "demo", 1])
    workbook.save(path)


def test_unchanged_file_is_loaded_from_index(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "index.sqlite3")
    database.initialize_database()
    source_dir = tmp_path / "reports"
    source_dir.mkdir()
    make_minimal_source(source_dir / "daily.xlsx")

    first = scan_reports(source_dir)
    second = scan_reports(source_dir)

    assert first["stats"] == {"found": 1, "read": 1, "from_index": 0}
    assert second["stats"] == {"found": 1, "read": 0, "from_index": 1}
