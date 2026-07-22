from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


# Канонические поля и их возможные заголовки во входном файле.
# Расширяйте списки, когда у нового источника другие названия колонок.
COLUMN_ALIASES: dict[str, list[str]] = {
    "status": ["status", "статус"],
    "termination_date": [
        "date of early termination",
        "date of termination",
        "early termination date",
        "дата досрочного расторжения",
        "дата раннего расторжения",
        "дата расторжения",
    ],
    "contract_number": [
        "contract number",
        "contract_number",
        "contract",
        "deal",
        "fk",
        "контракт",
        "номер контракта",
        "номер_контракта",
    ],
    "notional_amount": [
        "notional amount",
        "notional",
        "номинал",
        "номинал контракта",
    ],
    "notional_currency": [
        "cur of notional amount",
        "currency of notional amount",
        "notional currency",
        "валюта номинала",
    ],
    "quote": ["quote", "котировка"],
    "invested_amount": [
        "invested amount",
        "invested",
        "инвестированная сумма",
    ],
    "invested_currency": [
        "cur of invested amount",
        "currency of invested amount",
        "invested currency",
        "валюта инвестирования",
    ],
    "termination_amount": [
        "early termination amount",
        "termination amount",
        "сумма расторжения",
        "сумма к возврату",
        "сумма",
        "amount",
    ],
    "currency": [
        "cur of early termination amount",
        "currency of early termination amount",
        "валюта возврата",
        "валюта",
        "currency",
        "ccy",
    ],
}

# Порядок колонок в очищенном DataFrame.
ALL_CANONICAL_COLUMNS = (
    "status",
    "dissolution_type",
    "termination_date",
    "contract_number",
    "notional_amount",
    "notional_currency",
    "quote",
    "invested_amount",
    "invested_currency",
    "termination_amount",
    "currency",
)

# Колонки, без которых файл не считается корректным отчётом о расторжениях.
REQUIRED_CANONICAL_COLUMNS = (
    "contract_number",
    "termination_amount",
    "currency",
    "notional_amount",
    "termination_date",
)

# Типы расторжения по колонке Status.
DISSOLUTION_MANUAL = "manual"  # Status = "Created" → расторжение вручную
DISSOLUTION_MSSP = "mssp"      # прочие статусы (напр. "Uploaded WEB") → через МССП
DISSOLUTION_UNKNOWN = "unknown"


@dataclass
class IngestReport:
    input_rows: int
    output_rows: int
    dropped_empty_rows: int = 0
    ignored_incomplete_rows: int = 0
    dropped_duplicates: int = 0
    incomplete_row_examples: list[str] = field(default_factory=list)
    duplicate_warnings: list[str] = field(default_factory=list)
    latest_termination_date: date | None = None


def _normalize_header(value: object) -> str:
    normalized = str(value).replace("\xa0", " ").strip().lower()
    return " ".join(normalized.split())


def _alias_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        lookup[_normalize_header(canonical)] = canonical
        for alias in aliases:
            lookup[_normalize_header(alias)] = canonical
    return lookup


def _find_header_row(raw: pd.DataFrame) -> int:
    """Ищет строку заголовков в первых строках листа (над таблицей может быть мусор)."""
    lookup = _alias_lookup()
    best_row = -1
    best_score = 0
    limit = min(20, len(raw))
    for row_index in range(limit):
        recognized = set()
        for value in raw.iloc[row_index].tolist():
            canonical = lookup.get(_normalize_header(value))
            if canonical:
                recognized.add(canonical)
        if "contract_number" in recognized and len(recognized) > best_score:
            best_score = len(recognized)
            best_row = row_index
    if best_row < 0 or best_score < 3:
        raise ValueError(
            "Не найдена строка заголовков. Ожидались колонки Contract number, "
            "Early termination amount, валюта и т.д."
        )
    return best_row


def _rename_to_canonical(df: pd.DataFrame) -> pd.DataFrame:
    lookup = _alias_lookup()
    renamed = {}
    for column_name in df.columns:
        normalized = _normalize_header(column_name)
        renamed[column_name] = lookup.get(normalized, column_name)
    return df.rename(columns=renamed)


def _validate_required_columns(df: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_CANONICAL_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "Во входном файле не найдены обязательные колонки: " + ", ".join(missing)
        )


def _normalize_contract_number(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip()
    normalized = normalized.str.replace(r"\.0$", "", regex=True)
    return normalized.replace({"nan": "", "None": "", "<NA>": "", "NaT": ""})


def _normalize_currency(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip().str.upper()
    return text.replace({"NAN": "", "NONE": "", "<NA>": "", "NAT": ""})


def _normalize_number(series: pd.Series) -> pd.Series:
    """Числа в русском формате: '15 000 000,00' / '1,0115' → float."""
    as_text = series.astype(str).str.strip()
    as_text = as_text.str.replace("\xa0", "", regex=False).str.replace(" ", "", regex=False)
    as_text = as_text.str.replace(",", ".", regex=False)
    as_text = as_text.replace(
        {"nan": pd.NA, "None": pd.NA, "<NA>": pd.NA, "NaT": pd.NA, "": pd.NA}
    )
    return pd.to_numeric(as_text, errors="coerce")


def _normalize_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def _classify_dissolution(value: object) -> str:
    text = str(value or "").strip().casefold()
    if not text or text in {"nan", "none", "<na>", "nat"}:
        return DISSOLUTION_UNKNOWN
    if text == "created":
        return DISSOLUTION_MANUAL
    return DISSOLUTION_MSSP


def _collect_duplicate_warnings(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], int]:
    duplicate_mask = df.duplicated(subset=["contract_number"], keep=False)
    duplicate_rows = df[duplicate_mask]
    if duplicate_rows.empty:
        return df, [], 0

    warnings: list[str] = []
    for contract_number, group in duplicate_rows.groupby("contract_number", dropna=False):
        unique_amounts = sorted({str(value) for value in group["termination_amount"].tolist()})
        unique_currencies = sorted({str(value) for value in group["currency"].tolist()})
        if len(unique_amounts) > 1 or len(unique_currencies) > 1:
            warnings.append(
                f"Дубль контракта {contract_number}: "
                f"валюты={unique_currencies}, суммы={unique_amounts}"
            )
        else:
            warnings.append(f"Дубль контракта {contract_number}: одинаковые сумма и валюта")

    deduplicated = df.drop_duplicates(subset=["contract_number"], keep="first")
    dropped_duplicates = len(df) - len(deduplicated)
    return deduplicated, warnings, dropped_duplicates


def read_and_clean_excel(path: str) -> tuple[pd.DataFrame, IngestReport]:
    raw = pd.read_excel(path, engine="calamine", header=None, dtype=object)
    if raw.empty:
        raise ValueError("Файл пустой.")

    header_row = _find_header_row(raw)
    body = raw.iloc[header_row + 1:].reset_index(drop=True)
    body.columns = list(raw.iloc[header_row])

    df = _rename_to_canonical(body)
    df = df.loc[:, [column for column in df.columns if column in ALL_CANONICAL_COLUMNS]]
    df = df.loc[:, ~df.columns.duplicated()]
    _validate_required_columns(df)

    for column in ALL_CANONICAL_COLUMNS:
        if column == "dissolution_type":
            continue
        if column not in df.columns:
            df[column] = pd.NA

    report = IngestReport(input_rows=len(df), output_rows=0)

    before_drop_empty = len(df)
    df = df.dropna(how="all")
    report.dropped_empty_rows = before_drop_empty - len(df)

    df["contract_number"] = _normalize_contract_number(df["contract_number"])
    df["currency"] = _normalize_currency(df["currency"])
    df["notional_currency"] = _normalize_currency(df["notional_currency"])
    df["invested_currency"] = _normalize_currency(df["invested_currency"])
    df["termination_amount"] = _normalize_number(df["termination_amount"])
    df["notional_amount"] = _normalize_number(df["notional_amount"])
    df["invested_amount"] = _normalize_number(df["invested_amount"])
    df["quote"] = _normalize_number(df["quote"])
    df["termination_date"] = _normalize_date(df["termination_date"])
    df["status"] = (
        df["status"].astype(str).str.strip().replace({"nan": "", "None": "", "<NA>": "", "NaT": ""})
    )
    df["dissolution_type"] = df["status"].map(_classify_dissolution)

    # Частично заполненные строки не валят весь разбор — игнорируем и считаем.
    incomplete_mask = (
        df["contract_number"].eq("")
        | df["currency"].eq("")
        | df["termination_amount"].isna()
    )
    report.ignored_incomplete_rows = int(incomplete_mask.sum())
    if report.ignored_incomplete_rows:
        report.incomplete_row_examples = (
            df.loc[incomplete_mask, "contract_number"]
            .replace("", "<без номера>")
            .astype(str)
            .head(5)
            .tolist()
        )
        df = df.loc[~incomplete_mask].copy()

    if df.empty:
        raise ValueError(
            "Нет валидных строк: в каждой нужны номер контракта, сумма и валюта расторжения."
        )

    df, duplicate_warnings, dropped_duplicates = _collect_duplicate_warnings(df)
    report.duplicate_warnings = duplicate_warnings
    report.dropped_duplicates = dropped_duplicates
    report.output_rows = len(df)

    valid_dates = df["termination_date"].dropna()
    report.latest_termination_date = valid_dates.max().date() if not valid_dates.empty else None

    df = df[list(ALL_CANONICAL_COLUMNS)].reset_index(drop=True)
    return df, report
