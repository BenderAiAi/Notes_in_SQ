from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import pandas as pd

from .excel_ingest import (
    DISSOLUTION_MANUAL,
    DISSOLUTION_MSSP,
    DISSOLUTION_UNKNOWN,
    IngestReport,
)
from .report_builder import DEFAULT_CY_FIELD


# Уровни диагностики: error блокирует формирование, alert — важный красный флаг
# (кипрский контракт), warning — жёлтое предупреждение, notice — серая заметка.
LEVEL_ERROR = "error"
LEVEL_ALERT = "alert"
LEVEL_WARNING = "warning"
LEVEL_NOTICE = "notice"

DISSOLUTION_LABELS = {
    DISSOLUTION_MANUAL: "Ручное",
    DISSOLUTION_MSSP: "МССП",
    DISSOLUTION_UNKNOWN: "—",
}

# Абсолютный допуск при сравнении номинала из файла и из Mongo.
NOTIONAL_TOLERANCE = 0.01


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return str(value).strip().casefold() not in ("", "nan", "none", "nat", "<na>")


def _clean_text(value: Any) -> str:
    if not _is_filled(value):
        return ""
    return str(value).strip()


def _iso_date(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _index_by(mongo_df: pd.DataFrame, key: str) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if key not in mongo_df.columns:
        return index
    for _, row in mongo_df.iterrows():
        index[str(row[key])] = row.to_dict()
    return index


def build_analysis(
    clean_df: pd.DataFrame,
    ingest_report: IngestReport,
    mongo_df_1: pd.DataFrame,
    mongo_df_2: pd.DataFrame,
    *,
    cy_field: str = DEFAULT_CY_FIELD,
    rate_threshold: float = 1.0,
    file_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deals_by_id = _index_by(mongo_df_1, "SP_deal")
    trs_by_id = _index_by(mongo_df_2, "Number")

    contracts: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    notices: list[dict[str, Any]] = []

    not_found: list[str] = []
    notional_mismatch_count = 0
    cyprus_count = 0
    rates: list[float] = []
    by_currency: dict[str, dict[str, float]] = defaultdict(
        lambda: {"termination_sum": 0.0, "notional_sum": 0.0, "count": 0}
    )
    dubai_counts = {"total": 0, DISSOLUTION_MANUAL: 0, DISSOLUTION_MSSP: 0, DISSOLUTION_UNKNOWN: 0}
    trs_counts = {"total": 0, DISSOLUTION_MANUAL: 0, DISSOLUTION_MSSP: 0, DISSOLUTION_UNKNOWN: 0}

    for record in clean_df.to_dict("records"):
        contract_number = _clean_text(record.get("contract_number"))
        dissolution_type = str(record.get("dissolution_type") or DISSOLUTION_UNKNOWN)
        termination_amount = _to_float(record.get("termination_amount"))
        currency = _clean_text(record.get("currency"))
        notional_file = _to_float(record.get("notional_amount"))
        notional_currency = _clean_text(record.get("notional_currency"))

        deals_row = deals_by_id.get(contract_number)
        trs_row = trs_by_id.get(contract_number)
        in_dubai = deals_row is not None
        in_trs = trs_row is not None
        if in_dubai and in_trs:
            contract_type = "both"
        elif in_dubai:
            contract_type = "dubai"
        elif in_trs:
            contract_type = "trs"
        else:
            contract_type = "not_found"
        found = in_dubai or in_trs

        notional_mongo = None
        currency_mongo = None
        cyprus = False
        cyprus_value = None
        if in_dubai:
            notional_mongo = _to_float(deals_row.get("Notional"))
            currency_mongo = _clean_text(deals_row.get("Currency"))
            raw_cy = deals_row.get(cy_field)
            if _is_filled(raw_cy):
                cyprus = True
                cyprus_value = str(raw_cy).strip()
        elif in_trs:
            notional_mongo = _to_float(trs_row.get("Notional amount"))
            currency_mongo = _clean_text(trs_row.get("Currency"))

        rate_pct = None
        if termination_amount is not None and notional_file:
            rate_pct = termination_amount / notional_file * 100.0
            rates.append(rate_pct)
        rate_alert = rate_pct is not None and rate_pct > rate_threshold * 100.0

        notional_mismatch = (
            notional_file is not None
            and notional_mongo is not None
            and abs(notional_file - notional_mongo) > NOTIONAL_TOLERANCE
        )
        currency_mismatch = bool(
            notional_currency and currency_mongo and notional_currency != currency_mongo
        )

        contract = {
            "contract_number": contract_number,
            "type": contract_type,
            "found": found,
            "dissolution_type": dissolution_type,
            "dissolution_label": DISSOLUTION_LABELS.get(dissolution_type, "—"),
            "termination_date": _iso_date(record.get("termination_date")),
            "termination_amount": termination_amount,
            "currency": currency,
            "notional_file": notional_file,
            "notional_currency": notional_currency,
            "notional_mongo": notional_mongo,
            "currency_mongo": currency_mongo or None,
            "notional_mismatch": notional_mismatch,
            "currency_mismatch": currency_mismatch,
            "rate_pct": rate_pct,
            "rate_alert": rate_alert,
            "quote": _to_float(record.get("quote")),
            "invested_amount": _to_float(record.get("invested_amount")),
            "cyprus": cyprus,
            "cyprus_value": cyprus_value,
        }
        contracts.append(contract)

        # Агрегаты и диагностика по контракту.
        if currency:
            bucket = by_currency[currency]
            bucket["termination_sum"] += termination_amount or 0.0
            bucket["notional_sum"] += notional_file or 0.0
            bucket["count"] += 1

        if in_dubai:
            dubai_counts["total"] += 1
            dubai_counts[dissolution_type] = dubai_counts.get(dissolution_type, 0) + 1
        if in_trs:
            trs_counts["total"] += 1
            trs_counts[dissolution_type] = trs_counts.get(dissolution_type, 0) + 1

        if not found:
            not_found.append(contract_number)
        if contract_type == "both":
            warnings.append(_issue(LEVEL_WARNING, "found_in_both", contract_number,
                                   f"Контракт {contract_number} найден и в Dubai, и в TRS — попадёт в оба отчёта."))
        if cyprus:
            cyprus_count += 1
            alerts.append(_issue(LEVEL_ALERT, "cyprus_contract", contract_number,
                                 f"Контракт {contract_number}: есть связанный контракт на Кипре ({cyprus_value})."))
        if notional_mismatch:
            notional_mismatch_count += 1
            warnings.append(_issue(LEVEL_WARNING, "notional_mismatch", contract_number,
                                   f"Контракт {contract_number}: номинал в файле {_fmt(notional_file)} "
                                   f"≠ номинал в Mongo {_fmt(notional_mongo)}."))
        if currency_mismatch:
            warnings.append(_issue(LEVEL_WARNING, "currency_mismatch", contract_number,
                                   f"Контракт {contract_number}: валюта номинала в файле {notional_currency} "
                                   f"≠ в Mongo {currency_mongo}."))
        if found and not notional_file:
            warnings.append(_issue(LEVEL_WARNING, "no_notional", contract_number,
                                   f"Контракт {contract_number}: номинал не заполнен — ставка не рассчитана."))
        if rate_alert:
            warnings.append(_issue(LEVEL_WARNING, "rate_above_threshold", contract_number,
                                   f"Контракт {contract_number}: ставка {rate_pct:.3f}% превышает порог "
                                   f"{rate_threshold * 100:.2f}%."))

    if not_found:
        warnings.append(_issue(LEVEL_WARNING, "not_found", None,
                               "Не найдены в Mongo (будут пропущены при формировании): "
                               + ", ".join(not_found) + "."))

    found_count = sum(1 for contract in contracts if contract["found"])
    if found_count == 0:
        errors.append(_issue(LEVEL_ERROR, "no_found_contracts", None,
                             "Ни один контракт из файла не найден в Mongo — формировать нечего."))

    for warning in ingest_report.duplicate_warnings:
        notices.append(_issue(LEVEL_NOTICE, "duplicate", None, warning))
    if ingest_report.ignored_incomplete_rows:
        notices.append(_issue(LEVEL_NOTICE, "ignored_incomplete", None,
                              f"Пропущено неполных строк: {ingest_report.ignored_incomplete_rows} "
                              f"({', '.join(ingest_report.incomplete_row_examples)})."))

    meta = file_meta or {}
    if meta.get("latest_termination_date") and meta.get("today") and not meta.get("is_today"):
        warnings.append(_issue(LEVEL_WARNING, "date_not_today", None,
                               f"Дата расторжения в файле {_fmt_date(meta['latest_termination_date'])} "
                               "не совпадает с сегодняшней — проверьте, тот ли это файл."))

    summary = {
        "total": len(contracts),
        "found": found_count,
        "dubai": _counts_or_none(dubai_counts),
        "trs": _counts_or_none(trs_counts),
        "not_found": not_found,
        "notional_mismatches": notional_mismatch_count,
        "cyprus_count": cyprus_count,
        "rate": {
            "min": min(rates) if rates else None,
            "max": max(rates) if rates else None,
            "avg": sum(rates) / len(rates) if rates else None,
        },
        "by_currency": {
            currency: {
                "termination_sum": bucket["termination_sum"],
                "notional_sum": bucket["notional_sum"],
                "count": int(bucket["count"]),
            }
            for currency, bucket in sorted(by_currency.items())
        },
    }

    payload = {
        "path": meta.get("path"),
        "file_name": meta.get("file_name"),
        "modified_at": meta.get("modified_at"),
        "latest_termination_date": meta.get("latest_termination_date"),
        "today": meta.get("today"),
        "is_today": meta.get("is_today"),
        "contracts": contracts,
        "summary": summary,
        "errors": errors,
        "alerts": alerts,
        "warnings": warnings,
        "notices": notices,
        "can_generate": found_count > 0,
    }
    return payload


def _issue(level: str, code: str, contract: str | None, message: str) -> dict[str, Any]:
    return {"level": level, "code": code, "contract": contract, "message": message}


def _counts_or_none(counts: dict[str, int]) -> dict[str, int] | None:
    if counts["total"] == 0:
        return None
    return {
        "total": counts["total"],
        "manual": counts.get(DISSOLUTION_MANUAL, 0),
        "mssp": counts.get(DISSOLUTION_MSSP, 0),
        "unknown": counts.get(DISSOLUTION_UNKNOWN, 0),
    }


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}".replace(",", " ")


def _fmt_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return iso
