from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .database import cache_file, dictionary_map, get_cached_file, remove_stale_cache
from .excel import analyze_report, read_report


def eligible_excel_files(source_dir: Path) -> list[Path]:
    if not source_dir.is_dir():
        raise ValueError("Папка с исходными отчётами не существует или недоступна.")
    files = []
    for path in source_dir.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".xlsx":
            continue
        lowered = path.name.casefold()
        if lowered.startswith("~$") or lowered.startswith("note_trades_sq_"):
            continue
        files.append(path.resolve())
    return sorted(files, key=lambda item: item.name.casefold())


def scan_reports(source_dir: Path, force: bool = False) -> dict[str, Any]:
    dictionary = dictionary_map()
    files = eligible_excel_files(source_dir)
    results: list[dict[str, Any]] = []
    read_count = 0
    cached_count = 0
    for path in files:
        stat = path.stat()
        cached = None if force else get_cached_file(path, stat.st_size, stat.st_mtime_ns)
        if cached is not None:
            cached_count += 1
            # Ошибки справочника могли измениться, поэтому валидные данные проверяются заново при генерации.
            payload = cached
        else:
            payload = analyze_report(read_report(path), dictionary)
            cache_file(path, stat.st_size, stat.st_mtime_ns, payload)
            read_count += 1
        results.append(payload)

    remove_stale_cache({str(path) for path in files}, source_dir)
    recognized = [item for item in results if item.get("latest_trade_date")]
    recognized.sort(key=lambda item: (item["latest_trade_date"], item.get("modified_at") or ""), reverse=True)
    latest_date = recognized[0]["latest_trade_date"] if recognized else None
    candidates = [item for item in recognized if item["latest_trade_date"] == latest_date]
    today = date.today().isoformat()
    return {
        "files": recognized,
        "unrecognized": [item for item in results if not item.get("latest_trade_date")],
        "candidates": candidates,
        "latest_trade_date": latest_date,
        "is_today": latest_date == today,
        "today": today,
        "stats": {"found": len(files), "read": read_count, "from_index": cached_count},
    }
