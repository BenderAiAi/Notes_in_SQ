import os
from pathlib import Path

from notes_app.config import load_environment


def test_environment_is_loaded_from_explicit_file(
    tmp_path: Path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MONGO_URI=mongodb://example.test:27017/\n", encoding="utf-8"
    )
    monkeypatch.delenv("MONGO_URI", raising=False)

    assert load_environment(env_path) is True
    assert os.environ["MONGO_URI"] == "mongodb://example.test:27017/"


def test_environment_does_not_override_system_value(
    tmp_path: Path, monkeypatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MONGO_URI=mongodb://from-file.test:27017/\n", encoding="utf-8"
    )
    monkeypatch.setenv("MONGO_URI", "mongodb://system.test:27017/")

    load_environment(env_path)

    assert os.environ["MONGO_URI"] == "mongodb://system.test:27017/"
