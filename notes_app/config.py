from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("NOTEFLOW_DATA_DIR", PROJECT_ROOT / "data"))
SETTINGS_PATH = DATA_DIR / "settings.json"
DATABASE_PATH = DATA_DIR / "noteflow.sqlite3"


def load_environment(path: Path | None = None) -> bool:
    """Загружает локальный .env из корня проекта, не заменяя системные переменные."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    return bool(load_dotenv(path or PROJECT_ROOT / ".env", override=False))


load_environment()

DEFAULT_SETTINGS = {
    "source_dir": "",
    "output_dir": "",
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, str]:
    ensure_data_dir()
    if not SETTINGS_PATH.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        stored: Any = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SETTINGS.copy()
    return {
        key: str(stored.get(key, default)).strip()
        for key, default in DEFAULT_SETTINGS.items()
    }


def save_settings(source_dir: str, output_dir: str) -> dict[str, str]:
    ensure_data_dir()
    settings = {
        "source_dir": str(Path(source_dir).expanduser()) if source_dir.strip() else "",
        "output_dir": str(Path(output_dir).expanduser()) if output_dir.strip() else "",
    }
    temporary = SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(SETTINGS_PATH)
    return settings
