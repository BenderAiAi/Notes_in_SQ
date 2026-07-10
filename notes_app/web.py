from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file

from .config import DATA_DIR, load_settings, save_settings
from .database import (
    delete_dictionary_entry,
    dictionary_map,
    initialize_database,
    list_dictionary,
    save_dictionary_entry,
    upsert_dictionary_entries,
)
from .excel import (
    analyze_report,
    export_dictionary_workbook,
    generate_output,
    read_dictionary_workbook,
    read_report,
)
from .service import scan_reports


logger = logging.getLogger("noteflow")


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=20 * 1024 * 1024)
    if test_config:
        app.config.update(test_config)
    initialize_database()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/settings")
    def get_settings():
        return jsonify(load_settings())

    @app.put("/api/settings")
    def update_settings():
        payload = request.get_json(silent=True) or {}
        source_dir = str(payload.get("source_dir", "")).strip()
        output_dir = str(payload.get("output_dir", "")).strip()
        errors = []
        if source_dir and not Path(source_dir).expanduser().is_dir():
            errors.append("Папка с исходными отчётами не существует.")
        if output_dir:
            output_path = Path(output_dir).expanduser()
            try:
                output_path.mkdir(parents=True, exist_ok=True)
            except OSError:
                errors.append("Не удалось создать или открыть папку для готовых файлов.")
        if errors:
            return jsonify({"error": " ".join(errors)}), 400
        return jsonify(save_settings(source_dir, output_dir))

    @app.post("/api/browse-folder")
    def browse_folder():
        payload = request.get_json(silent=True) or {}
        initial = str(payload.get("initial", "")).strip()
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(
                initialdir=initial if initial and Path(initial).is_dir() else None,
                mustexist=True,
            )
            root.destroy()
            return jsonify({"path": selected})
        except Exception as exc:
            return jsonify({"error": f"Не удалось открыть выбор папки: {exc}. Путь можно ввести вручную."}), 500

    @app.post("/api/reports/scan")
    def reports_scan():
        payload = request.get_json(silent=True) or {}
        settings = load_settings()
        source_dir_text = str(payload.get("source_dir") or settings["source_dir"]).strip()
        output_dir = str(payload.get("output_dir") or settings["output_dir"])
        if not source_dir_text:
            return jsonify({"error": "Сначала укажите папку с исходными отчётами."}), 400
        source_dir = Path(source_dir_text).expanduser()
        try:
            logger.info("Проверяю отчёты в папке: %s", source_dir)
            saved = save_settings(str(source_dir), output_dir)
            result = scan_reports(source_dir, force=bool(payload.get("force")))
            result["settings"] = saved
            logger.info(
                "Найдено файлов: %s · прочитано: %s · из индекса: %s",
                result["stats"]["found"], result["stats"]["read"], result["stats"]["from_index"],
            )
            return jsonify(result)
        except ValueError as exc:
            logger.warning("Проверка не выполнена: %s", exc)
            return jsonify({"error": str(exc)}), 400
        except OSError as exc:
            logger.error("Не удалось прочитать папку: %s", exc)
            return jsonify({"error": f"Не удалось прочитать папку: {exc}"}), 500

    @app.post("/api/reports/analyze")
    def report_analyze():
        payload = request.get_json(silent=True) or {}
        try:
            path = _allowed_source_file(str(payload.get("path", "")))
            return jsonify(analyze_report(read_report(path), dictionary_map()))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.post("/api/reports/generate")
    def report_generate():
        payload = request.get_json(silent=True) or {}
        try:
            source_path = _allowed_source_file(str(payload.get("path", "")))
            output_dir_text = load_settings().get("output_dir", "")
            if not output_dir_text:
                raise ValueError("Сначала укажите папку для готовых файлов.")
            output_dir = Path(output_dir_text).expanduser()
            parsed = read_report(source_path)
            analysis = analyze_report(parsed, dictionary_map())
            if not analysis["can_generate"]:
                return jsonify({"error": "Исправьте блокирующие ошибки перед формированием.", "analysis": analysis}), 422
            report_date = max(record["trade_date"] for record in parsed.records if record["trade_date"])
            expected = output_dir / f"Note_trades_sq_{report_date:%d%m%Y}.xlsx"
            if expected.exists() and not bool(payload.get("overwrite")):
                return jsonify({"error": "Файл с таким именем уже существует.", "requires_overwrite": True, "path": str(expected)}), 409
            output_path = generate_output(parsed, dictionary_map(), output_dir)
            logger.info("Сформирован файл: %s", output_path)
            return jsonify({
                "ok": True,
                "path": str(output_path),
                "file_name": output_path.name,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            })
        except ValueError as exc:
            logger.warning("Файл не сформирован: %s", exc)
            return jsonify({"error": str(exc)}), 400
        except OSError as exc:
            logger.error("Ошибка сохранения: %s", exc)
            return jsonify({"error": f"Не удалось сохранить файл: {exc}"}), 500

    @app.get("/api/dictionary")
    def dictionary_list():
        return jsonify({"items": list_dictionary(request.args.get("search", ""))})

    @app.post("/api/dictionary")
    def dictionary_create():
        try:
            entry = save_dictionary_entry(request.get_json(silent=True) or {})
            logger.info("В справочник добавлен ISIN %s", entry["isin"])
            return jsonify(entry), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.put("/api/dictionary/<int:entry_id>")
    def dictionary_update(entry_id: int):
        try:
            entry = save_dictionary_entry(request.get_json(silent=True) or {}, entry_id)
            logger.info("В справочнике обновлён ISIN %s", entry["isin"])
            return jsonify(entry)
        except (ValueError, LookupError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.delete("/api/dictionary/<int:entry_id>")
    def dictionary_delete(entry_id: int):
        if not delete_dictionary_entry(entry_id):
            return jsonify({"error": "Запись не найдена."}), 404
        logger.info("Из справочника удалена запись #%s", entry_id)
        return jsonify({"ok": True})

    @app.post("/api/dictionary/import")
    def dictionary_import():
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"error": "Выберите Excel-файл справочника."}), 400
        if not uploaded.filename.casefold().endswith(".xlsx"):
            return jsonify({"error": "Поддерживаются только файлы .xlsx."}), 400
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False, dir=DATA_DIR) as temporary:
                uploaded.save(temporary)
                temporary_path = Path(temporary.name)
            entries = read_dictionary_workbook(temporary_path)
            created, updated = upsert_dictionary_entries(entries)
            logger.info("Импорт справочника: добавлено %s · обновлено %s", created, updated)
            return jsonify({"ok": True, "created": created, "updated": updated, "total": len(entries)})
        except (ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    @app.get("/api/dictionary/export")
    def dictionary_export():
        export_path = DATA_DIR / "Note_dictionary.xlsx"
        export_dictionary_workbook(list_dictionary(), export_path)
        return send_file(export_path, as_attachment=True, download_name="Note_dictionary.xlsx")

    @app.errorhandler(413)
    def file_too_large(_error):
        return jsonify({"error": "Файл слишком большой. Максимальный размер — 20 МБ."}), 413

    return app


def _allowed_source_file(raw_path: str) -> Path:
    settings = load_settings()
    if not settings.get("source_dir"):
        raise ValueError("Сначала укажите папку с исходными отчётами.")
    source_dir = Path(settings["source_dir"]).expanduser().resolve()
    path = Path(raw_path).expanduser().resolve()
    if path.parent != source_dir or not path.is_file() or path.suffix.casefold() != ".xlsx":
        raise ValueError("Выбранный файл не относится к настроенной папке отчётов.")
    if path.name.startswith("~$") or path.name.casefold().startswith("note_trades_sq_"):
        raise ValueError("Этот файл нельзя использовать как исходный отчёт.")
    return path
