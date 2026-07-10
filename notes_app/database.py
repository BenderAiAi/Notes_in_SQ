from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import DATABASE_PATH, ensure_data_dir


DICTIONARY_FIELDS = (
    "note",
    "isin",
    "note_name_sq",
    "portfolio",
    "subportfolio",
    "subaccount",
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
            CREATE TABLE IF NOT EXISTS dictionary_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note TEXT NOT NULL DEFAULT '',
                isin TEXT NOT NULL COLLATE NOCASE UNIQUE,
                note_name_sq TEXT NOT NULL DEFAULT '',
                portfolio TEXT NOT NULL DEFAULT '',
                subportfolio TEXT NOT NULL DEFAULT '',
                subaccount TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS file_index (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                latest_trade_date TEXT,
                row_count INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                scanned_at TEXT NOT NULL
            );
            """
        )


def _clean_entry(data: dict[str, Any]) -> dict[str, str]:
    return {field: str(data.get(field, "") or "").strip() for field in DICTIONARY_FIELDS}


def list_dictionary(search: str = "") -> list[dict[str, Any]]:
    query = "SELECT * FROM dictionary_entries"
    parameters: list[Any] = []
    if search.strip():
        term = f"%{search.strip()}%"
        query += " WHERE isin LIKE ? OR note LIKE ? OR note_name_sq LIKE ?"
        parameters.extend([term, term, term])
    query += " ORDER BY isin COLLATE NOCASE"
    with connect() as connection:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def dictionary_map() -> dict[str, dict[str, Any]]:
    return {entry["isin"].strip().upper(): entry for entry in list_dictionary()}


def save_dictionary_entry(data: dict[str, Any], entry_id: int | None = None) -> dict[str, Any]:
    cleaned = _clean_entry(data)
    if not cleaned["isin"]:
        raise ValueError("ISIN обязателен.")
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as connection:
        try:
            if entry_id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO dictionary_entries
                    (note, isin, note_name_sq, portfolio, subportfolio, subaccount, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [cleaned[field] for field in DICTIONARY_FIELDS] + [now, now],
                )
                entry_id = int(cursor.lastrowid)
            else:
                result = connection.execute(
                    """
                    UPDATE dictionary_entries
                    SET note=?, isin=?, note_name_sq=?, portfolio=?, subportfolio=?, subaccount=?, updated_at=?
                    WHERE id=?
                    """,
                    [cleaned[field] for field in DICTIONARY_FIELDS] + [now, entry_id],
                )
                if result.rowcount == 0:
                    raise LookupError("Запись справочника не найдена.")
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"ISIN {cleaned['isin']} уже есть в справочнике.") from exc
        row = connection.execute(
            "SELECT * FROM dictionary_entries WHERE id=?", (entry_id,)
        ).fetchone()
    return dict(row)


def delete_dictionary_entry(entry_id: int) -> bool:
    with connect() as connection:
        result = connection.execute("DELETE FROM dictionary_entries WHERE id=?", (entry_id,))
        return result.rowcount > 0


def upsert_dictionary_entries(entries: list[dict[str, Any]]) -> tuple[int, int]:
    created = 0
    updated = 0
    for entry in entries:
        cleaned = _clean_entry(entry)
        if not cleaned["isin"]:
            continue
        existing = next(
            (item for item in list_dictionary(cleaned["isin"]) if item["isin"].upper() == cleaned["isin"].upper()),
            None,
        )
        save_dictionary_entry(cleaned, existing["id"] if existing else None)
        if existing:
            updated += 1
        else:
            created += 1
    return created, updated


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
                (path, size, mtime_ns, file_name, latest_trade_date, row_count, payload, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                size=excluded.size,
                mtime_ns=excluded.mtime_ns,
                file_name=excluded.file_name,
                latest_trade_date=excluded.latest_trade_date,
                row_count=excluded.row_count,
                payload=excluded.payload,
                scanned_at=excluded.scanned_at
            """,
            (
                str(path),
                size,
                mtime_ns,
                path.name,
                payload.get("latest_trade_date"),
                payload.get("summary", {}).get("rows", 0),
                json.dumps(payload, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def remove_stale_cache(known_paths: set[str], source_dir: Path) -> None:
    prefix = str(source_dir.resolve())
    with connect() as connection:
        rows = connection.execute("SELECT path FROM file_index").fetchall()
        stale = [row["path"] for row in rows if row["path"].startswith(prefix) and row["path"] not in known_paths]
        connection.executemany("DELETE FROM file_index WHERE path=?", [(path,) for path in stale])
