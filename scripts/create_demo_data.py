from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from notes_app.excel import DICTIONARY_HEADERS, SOURCE_HEADERS


DEMO = ROOT / "demo"


def create_report() -> Path:
    reports = DEMO / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    today = date.today()
    settlement = today + timedelta(days=3)
    path = reports / f"Торги нотами {today:%d.%m.%Y}.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Сделки"
    sheet.append([None, *SOURCE_HEADERS])
    sheet.append([1, "2 991 432", today, settlement, "10:37:14", "XS2777123369", "Купля", "41,01", 35, "1 323,57", "SUR", "USD", "DEMO/1", "249 235"])
    sheet.append([2, "2 991 433", today, settlement, "11:01:57", "XS2777123369", "Продажа", "41,01", 9, "3 312,55", "SUR", "USD", "DEMO/2", "249 235"])
    workbook.save(path)
    return path


def create_dictionary() -> Path:
    DEMO.mkdir(parents=True, exist_ok=True)
    path = DEMO / "Note_dictionary_demo.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "dictionary"
    sheet.append(DICTIONARY_HEADERS)
    sheet.append(["Demo note", "XS2777123369", "series DEMO isin:XS2777123369", "EMTN Demo SP", "Phoenixes demo", "DEMO: Phoenix Notes"])
    workbook.save(path)
    return path


if __name__ == "__main__":
    report = create_report()
    dictionary = create_dictionary()
    (DEMO / "ready").mkdir(exist_ok=True)
    print(f"Создан отчёт: {report}")
    print(f"Создан справочник: {dictionary}")
    print(f"Папка результатов: {DEMO / 'ready'}")
