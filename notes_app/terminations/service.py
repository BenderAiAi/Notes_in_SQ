from __future__ import annotations

import time as time_module
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .database import cache_file, get_cached_file, remove_stale_cache
from .excel_ingest import read_and_clean_excel


# Имена готовых отчётов, которые сами являются выходом сервиса — их не разбираем как источник.
OUTPUT_SUFFIXES = ("-dubai_term.xlsx", "-trs_term.xlsx")


def eligible_excel_files(source_dir: Path) -> list[Path]:
    if not source_dir.is_dir():
        raise ValueError("Папка с исходными файлами не существует или недоступна.")
    files = []
    for path in source_dir.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".xlsx":
            continue
        lowered = path.name.casefold()
        if lowered.startswith("~$") or lowered.endswith(OUTPUT_SUFFIXES):
            continue
        files.append(path.resolve())
    return sorted(files, key=lambda item: item.name.casefold())


def _read_with_retry(path: Path):
    """IO-ошибки (файл ещё дописывается почтой/выгрузкой) повторяем; ValueError — это не отчёт."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return read_and_clean_excel(str(path))
        except ValueError:
            raise
        except (PermissionError, OSError) as exc:
            last_error = exc
            if attempt < 2:
                time_module.sleep(0.25 * (attempt + 1))
    assert last_error is not None
    raise last_error


def _summarize_file(path: Path, stat) -> dict[str, Any]:
    modified_at = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    base = {
        "path": str(path),
        "file_name": path.name,
        "modified_at": modified_at,
        "latest_termination_date": None,
    }
    try:
        clean_df, report = _read_with_retry(path)
    except ValueError as exc:
        return {**base, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — показываем пользователю понятную причину
        return {**base, "error": f"Не удалось прочитать файл: {exc}"}

    type_counts = clean_df["dissolution_type"].value_counts().to_dict()
    currencies = sorted({value for value in clean_df["currency"].tolist() if value})
    return {
        **base,
        "latest_termination_date": (
            report.latest_termination_date.isoformat() if report.latest_termination_date else None
        ),
        "row_count": int(report.output_rows),
        "manual_count": int(type_counts.get("manual", 0)),
        "mssp_count": int(type_counts.get("mssp", 0)),
        "unknown_count": int(type_counts.get("unknown", 0)),
        "currencies": currencies,
    }


def scan_reports(source_dir: Path, force: bool = False) -> dict[str, Any]:
    files = eligible_excel_files(source_dir)
    results: list[dict[str, Any]] = []
    read_count = 0
    cached_count = 0
    for path in files:
        stat = path.stat()
        cached = None if force else get_cached_file(path, stat.st_size, stat.st_mtime_ns)
        if cached is not None and cached.get("latest_termination_date"):
            cached_count += 1
            payload = cached
        else:
            payload = _summarize_file(path, stat)
            # Ошибку чтения не фиксируем в индексе навсегда — следующая проверка попробует снова.
            if payload.get("latest_termination_date"):
                cache_file(path, stat.st_size, stat.st_mtime_ns, payload)
            read_count += 1
        results.append(payload)

    remove_stale_cache({str(path) for path in files}, source_dir)
    recognized = [item for item in results if item.get("latest_termination_date")]
    recognized.sort(
        key=lambda item: (item["latest_termination_date"], item.get("modified_at") or ""),
        reverse=True,
    )
    latest_date = recognized[0]["latest_termination_date"] if recognized else None
    candidates = [item for item in recognized if item["latest_termination_date"] == latest_date]
    today = date.today().isoformat()
    return {
        "files": recognized,
        "unrecognized": [item for item in results if not item.get("latest_termination_date")],
        "candidates": candidates,
        "latest_termination_date": latest_date,
        "is_today": latest_date == today,
        "today": today,
        "stats": {"found": len(files), "read": read_count, "from_index": cached_count},
    }
