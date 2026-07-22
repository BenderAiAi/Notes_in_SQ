from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file

from .analysis import build_analysis
from .config import DATA_DIR, load_settings, save_settings
from .database import (
    history_summary,
    initialize_database,
    list_history,
    record_terminations,
)
from .excel_ingest import read_and_clean_excel
from .mongo_client import fetch_contract_data, get_client, load_mongo_settings
from .output import existing_outputs, export_history_workbook, generate_reports
from .service import OUTPUT_SUFFIXES, scan_reports


logger = logging.getLogger("dubai_term")


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=20 * 1024 * 1024)
    if test_config:
        app.config.update(test_config)
    initialize_database()

    @app.get("/")
    def index():
        return "NoteFlow · Расторжения Dubai/TRS API"

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
            errors.append("Папка с исходными файлами не существует.")
        if output_dir:
            try:
                Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
            except OSError:
                errors.append("Не удалось создать или открыть папку для готовых отчётов.")
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
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Не удалось открыть выбор папки: {exc}. Путь можно ввести вручную."}), 500

    @app.post("/api/reports/scan")
    def reports_scan():
        payload = request.get_json(silent=True) or {}
        settings = load_settings()
        source_dir_text = str(payload.get("source_dir") or settings["source_dir"]).strip()
        output_dir = str(payload.get("output_dir") or settings["output_dir"])
        if not source_dir_text:
            return jsonify({"error": "Сначала укажите папку с исходными файлами."}), 400
        source_dir = Path(source_dir_text).expanduser()
        try:
            logger.info("Проверяю файлы в папке: %s", source_dir)
            saved = save_settings(str(source_dir), output_dir)
            result = scan_reports(source_dir, force=bool(payload.get("force")))
            result["settings"] = saved
            logger.info(
                "Найдено: %s · прочитано: %s · из индекса: %s",
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
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        try:
            return jsonify(_analyze_path(path))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 — чаще всего недоступна Mongo
            logger.error("Анализ не выполнен: %s", exc)
            return jsonify({"error": f"Не удалось получить данные из Mongo: {exc}"}), 502

    @app.post("/api/reports/generate")
    def report_generate():
        payload = request.get_json(silent=True) or {}
        try:
            path = _allowed_source_file(str(payload.get("path", "")))
            output_dir_text = load_settings().get("output_dir", "")
            if not output_dir_text:
                raise ValueError("Сначала укажите папку для готовых отчётов.")
            output_dir = Path(output_dir_text).expanduser()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        try:
            clean_df, report, mongo_df_1, mongo_df_2, mongo_settings = _load_file_and_mongo(path)
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            logger.error("Чтение Mongo не выполнено: %s", exc)
            return jsonify({"error": f"Не удалось получить данные из Mongo: {exc}"}), 502

        analysis = build_analysis(
            clean_df, report, mongo_df_1, mongo_df_2,
            cy_field=mongo_settings.cy_field,
            rate_threshold=_rate_threshold(),
            file_meta=_file_meta(path, report),
        )
        if not analysis["can_generate"]:
            return jsonify({
                "error": "Ни один контракт из файла не найден в Mongo — формировать нечего.",
                "analysis": analysis,
            }), 422

        today_date = datetime.today().strftime("%d-%m-%Y")
        existing = existing_outputs(today_date, output_dir)
        if existing and not bool(payload.get("overwrite")):
            return jsonify({
                "error": "Файлы с такими именами уже существуют.",
                "requires_overwrite": True,
                "files": existing,
            }), 409

        try:
            saved = generate_reports(
                clean_df, mongo_df_1, mongo_df_2, today_date, output_dir, mongo_settings.cy_field
            )
        except OSError as exc:
            logger.error("Ошибка сохранения: %s", exc)
            return jsonify({"error": f"Не удалось сохранить файлы: {exc}"}), 500

        created, updated = record_terminations(_history_entries(analysis, path.name))
        logger.info(
            "Сформировано: Dubai=%s · TRS=%s · история +%s ~%s",
            saved["dubai_count"], saved["trs_count"], created, updated,
        )
        return jsonify({
            "ok": True,
            "saved": saved,
            "history": {"created": created, "updated": updated},
            "analysis": analysis,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    @app.get("/api/history")
    def history_list():
        return jsonify({
            "items": list_history(
                search=request.args.get("search", ""),
                currency=request.args.get("currency", ""),
                date_from=request.args.get("date_from", ""),
                date_to=request.args.get("date_to", ""),
            ),
            "summary": history_summary(),
        })

    @app.get("/api/history/export")
    def history_export():
        rows = list_history(
            search=request.args.get("search", ""),
            currency=request.args.get("currency", ""),
            date_from=request.args.get("date_from", ""),
            date_to=request.args.get("date_to", ""),
        )
        export_path = DATA_DIR / "termination_history.xlsx"
        export_history_workbook(rows, export_path)
        return send_file(export_path, as_attachment=True, download_name="termination_history.xlsx")

    @app.errorhandler(413)
    def file_too_large(_error):
        return jsonify({"error": "Файл слишком большой."}), 413

    return app


# ---------------------------------------------------------------------------
# Вспомогательные функции.
# ---------------------------------------------------------------------------

def _rate_threshold() -> float:
    try:
        return float(os.getenv("RATE_ALERT_THRESHOLD", "1.0"))
    except ValueError:
        return 1.0


def _allowed_source_file(raw_path: str) -> Path:
    settings = load_settings()
    if not settings.get("source_dir"):
        raise ValueError("Сначала укажите папку с исходными файлами.")
    source_dir = Path(settings["source_dir"]).expanduser().resolve()
    path = Path(raw_path).expanduser().resolve()
    if path.parent != source_dir or not path.is_file() or path.suffix.casefold() != ".xlsx":
        raise ValueError("Выбранный файл не относится к настроенной папке.")
    if path.name.startswith("~$") or path.name.casefold().endswith(OUTPUT_SUFFIXES):
        raise ValueError("Этот файл нельзя использовать как исходный.")
    return path


def _load_file_and_mongo(path: Path):
    clean_df, report = read_and_clean_excel(str(path))
    settings = load_mongo_settings()
    client = get_client(settings)
    try:
        mongo_df_1, mongo_df_2 = fetch_contract_data(
            client, settings, clean_df["contract_number"].tolist()
        )
    finally:
        client.close()
    return clean_df, report, mongo_df_1, mongo_df_2, settings


def _analyze_path(path: Path) -> dict[str, Any]:
    clean_df, report, mongo_df_1, mongo_df_2, settings = _load_file_and_mongo(path)
    return build_analysis(
        clean_df, report, mongo_df_1, mongo_df_2,
        cy_field=settings.cy_field,
        rate_threshold=_rate_threshold(),
        file_meta=_file_meta(path, report),
    )


def _file_meta(path: Path, report) -> dict[str, Any]:
    stat = path.stat()
    latest = report.latest_termination_date.isoformat() if report.latest_termination_date else None
    today = date.today().isoformat()
    return {
        "path": str(path),
        "file_name": path.name,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "latest_termination_date": latest,
        "today": today,
        "is_today": latest == today,
    }


def _history_entries(analysis: dict[str, Any], source_file: str) -> list[dict[str, Any]]:
    entries = []
    for contract in analysis["contracts"]:
        if not contract["found"]:
            continue
        entries.append({
            "contract_number": contract["contract_number"],
            "termination_date": contract["termination_date"] or "",
            "contract_type": contract["type"],
            "rate_pct": contract["rate_pct"],
            "termination_amount": contract["termination_amount"],
            "return_currency": contract["currency"],
            "notional": contract["notional_file"],
            "notional_currency": contract["notional_currency"],
            "dissolution_type": contract["dissolution_type"],
            "cyprus_flag": contract["cyprus"],
            "source_file": source_file,
        })
    return entries
