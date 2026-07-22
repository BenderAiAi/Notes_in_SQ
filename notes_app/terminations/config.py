from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, ensure_data_dir


SETTINGS_PATH = DATA_DIR / "termination_settings.json"
DATABASE_PATH = DATA_DIR / "termination_history.sqlite3"

DEFAULT_SETTINGS = {
    "source_dir": "",
    "output_dir": "",
}


def load_settings() -> dict[str, str]:
    ensure_data_dir()
    if not SETTINGS_PATH.exists():
        settings = DEFAULT_SETTINGS.copy()
        env_output = os.environ.get("TERMINATION_OUTPUT_DIR", "").strip()
        if env_output:
            settings["output_dir"] = str(Path(env_output).expanduser())
        return settings
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
