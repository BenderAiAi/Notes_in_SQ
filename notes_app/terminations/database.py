from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import DATABASE_PATH, ensure_data_dir


HISTORY_FIELDS = (
    "contract_number",
    "termination_date",
    "contract_type",
    "rate_pct",
    "termination_amount",
    "return_currency",
    "notional",
    "notional_currency",
    "dissolution_type",
    "cyprus_flag",
    "source_file",
)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_data_dir()
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS file_index (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                latest_termination_date TEXT,
                row_count INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                scanned_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS termination_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_number TEXT NOT NULL,
                termination_date TEXT NOT NULL DEFAULT '',
                contract_type TEXT NOT NULL DEFAULT '',
                rate_pct REAL,
                termination_amount REAL,
                return_currency TEXT NOT NULL DEFAULT '',
                notional REAL,
                notional_currency TEXT NOT NULL DEFAULT '',
                dissolution_type TEXT NOT NULL DEFAULT '',
                cyprus_flag INTEGER NOT NULL DEFAULT 0,
                source_file TEXT NOT NULL DEFAULT '',
                recorded_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(contract_number, termination_date)
            );
            """
        )


# ---------------------------------------------------------------------------
# Индекс просмотренных файлов (кэш выбора актуального отчёта).
# ---------------------------------------------------------------------------

def get_cached_file(path: Path, size: int, mtime_ns: int) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM file_index WHERE path=? AND size=? AND mtime_ns=?",
            (str(path), size, mtime_ns),
        ).fetchone()
    if not row:
        return None
    return json.loads(row["payload"])


def cache_file(path: Path, size: int, mtime_ns: int, payload: dict[str, Any]) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO file_index
                (path, size, mtime_ns, file_name, latest_termination_date, row_count, payload, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                size=excluded.size,
                mtime_ns=excluded.mtime_ns,
                file_name=excluded.file_name,
                latest_termination_date=excluded.latest_termination_date,
                row_count=excluded.row_count,
                payload=excluded.payload,
                scanned_at=excluded.scanned_at
            """,
            (
                str(path),
                size,
                mtime_ns,
                path.name,
                payload.get("latest_termination_date"),
                int(payload.get("row_count", 0) or 0),
                json.dumps(payload, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def remove_stale_cache(known_paths: set[str], source_dir: Path) -> None:
    prefix = str(source_dir.resolve())
    with connect() as connection:
        rows = connection.execute("SELECT path FROM file_index").fetchall()
        stale = [
            row["path"]
            for row in rows
            if row["path"].startswith(prefix) and row["path"] not in known_paths
        ]
        connection.executemany("DELETE FROM file_index WHERE path=?", [(path,) for path in stale])


# ---------------------------------------------------------------------------
# История расторжений (upsert по contract_number + termination_date).
# ---------------------------------------------------------------------------

def _clean_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_number": str(entry.get("contract_number", "") or "").strip(),
        "termination_date": str(entry.get("termination_date", "") or "").strip(),
        "contract_type": str(entry.get("contract_type", "") or "").strip(),
        "rate_pct": entry.get("rate_pct"),
        "termination_amount": entry.get("termination_amount"),
        "return_currency": str(entry.get("return_currency", "") or "").strip(),
        "notional": entry.get("notional"),
        "notional_currency": str(entry.get("notional_currency", "") or "").strip(),
        "dissolution_type": str(entry.get("dissolution_type", "") or "").strip(),
        "cyprus_flag": 1 if entry.get("cyprus_flag") else 0,
        "source_file": str(entry.get("source_file", "") or "").strip(),
    }


def record_terminations(entries: list[dict[str, Any]]) -> tuple[int, int]:
    """Сохраняет расторжения в историю. Возвращает (добавлено, обновлено)."""
    created = 0
    updated = 0
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as connection:
        for raw in entries:
            entry = _clean_history_entry(raw)
            if not entry["contract_number"]:
                continue
            existing = connection.execute(
                "SELECT id FROM termination_history WHERE contract_number=? AND termination_date=?",
                (entry["contract_number"], entry["termination_date"]),
            ).fetchone()
            connection.execute(
                """
                INSERT INTO termination_history
                    (contract_number, termination_date, contract_type, rate_pct, termination_amount,
                     return_currency, notional, notional_currency, dissolution_type, cyprus_flag,
                     source_file, recorded_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(contract_number, termination_date) DO UPDATE SET
                    contract_type=excluded.contract_type,
                    rate_pct=excluded.rate_pct,
                    termination_amount=excluded.termination_amount,
                    return_currency=excluded.return_currency,
                    notional=excluded.notional,
                    notional_currency=excluded.notional_currency,
                    dissolution_type=excluded.dissolution_type,
                    cyprus_flag=excluded.cyprus_flag,
                    source_file=excluded.source_file,
                    updated_at=excluded.updated_at
                """,
                (
                    entry["contract_number"], entry["termination_date"], entry["contract_type"],
                    entry["rate_pct"], entry["termination_amount"], entry["return_currency"],
                    entry["notional"], entry["notional_currency"], entry["dissolution_type"],
                    entry["cyprus_flag"], entry["source_file"], now, now,
                ),
            )
            if existing:
                updated += 1
            else:
                created += 1
    return created, updated


def list_history(
    search: str = "",
    currency: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    query = "SELECT * FROM termination_history"
    clauses: list[str] = []
    parameters: list[Any] = []
    if search.strip():
        clauses.append("contract_number LIKE ?")
        parameters.append(f"%{search.strip()}%")
    if currency.strip():
        clauses.append("return_currency = ?")
        parameters.append(currency.strip().upper())
    if date_from.strip():
        clauses.append("termination_date >= ?")
        parameters.append(date_from.strip())
    if date_to.strip():
        clauses.append("termination_date <= ?")
        parameters.append(date_to.strip())
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY termination_date DESC, updated_at DESC"
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def history_summary() -> dict[str, Any]:
    with connect() as connection:
        total = connection.execute("SELECT COUNT(*) AS c FROM termination_history").fetchone()["c"]
        by_currency = connection.execute(
            """
            SELECT return_currency AS currency,
                   COUNT(*) AS count,
                   SUM(termination_amount) AS termination_sum
            FROM termination_history
            GROUP BY return_currency
            ORDER BY return_currency
            """
        ).fetchall()
    return {
        "total": int(total),
        "by_currency": [
            {
                "currency": row["currency"] or "—",
                "count": int(row["count"]),
                "termination_sum": float(row["termination_sum"] or 0.0),
            }
            for row in by_currency
        ],
    }
