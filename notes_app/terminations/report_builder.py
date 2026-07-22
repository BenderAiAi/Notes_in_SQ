from __future__ import annotations

from datetime import datetime

import pandas as pd


DEFAULT_CY_FIELD = "fc_num_on_CY_old"

FINAL_COLUMNS_DUBAI = [
    "Номер форвардного контракта",
    "№ соглашения о расторжении",
    "Дата заключения",
    "Дата расторжения (план)",
    "Дата расторжения",
    "Номинал контракта",
    "Валюта номинала",
    "Номер счета",
    "Сумма к возврату",
    "Валюта возврата",
    "Тип ФК",
    "Базисный актив",
    "Значение закрытия базисного актива",
    "fc_num_on_CY_old",
]

FINAL_COLUMNS_TRS = [
    "Номер форвардного контракта",
    "№ соглашения о расторжении",
    "Дата заключения",
    "Дата расторжения",
    "Дата расторжения (план)",
    "Номинал контракта",
    "Валюта номинала",
    "Номер счета",
    "Сумма к возврату",
    "Валюта возврата",
    "Тип ФК",
    "Базисный актив",
    "Значение закрытия базисного актива",
]


def contracts_found_in_mongo(mongo_df_1: pd.DataFrame, mongo_df_2: pd.DataFrame) -> set[str]:
    from_deals = set(mongo_df_1["SP_deal"].tolist()) if "SP_deal" in mongo_df_1.columns else set()
    from_trs = set(mongo_df_2["Number"].tolist()) if "Number" in mongo_df_2.columns else set()
    return {str(value) for value in from_deals.union(from_trs)}


def missing_contracts(
    input_contract_numbers: list[str], mongo_df_1: pd.DataFrame, mongo_df_2: pd.DataFrame
) -> list[str]:
    found = contracts_found_in_mongo(mongo_df_1, mongo_df_2)
    return sorted(set(map(str, input_contract_numbers)) - found)


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column not in df.columns:
            df[column] = ""
    return df


def _normalize_output_types(df: pd.DataFrame) -> pd.DataFrame:
    if "Сумма к возврату" in df.columns:
        df["Сумма к возврату"] = pd.to_numeric(df["Сумма к возврату"], errors="raise")
    if "Номинал контракта" in df.columns:
        df["Номинал контракта"] = pd.to_numeric(df["Номинал контракта"], errors="coerce")
    for date_column in ("Дата заключения", "Дата расторжения", "Дата расторжения (план)"):
        if date_column in df.columns:
            df[date_column] = pd.to_datetime(df[date_column], errors="coerce", dayfirst=True)
    return df


def build_dubai_report(
    mongo_df_1: pd.DataFrame,
    clean_df: pd.DataFrame,
    today_date: str,
    cy_field: str = DEFAULT_CY_FIELD,
) -> pd.DataFrame:
    if "SP_deal" not in mongo_df_1.columns:
        return pd.DataFrame()

    merged = pd.merge(
        mongo_df_1,
        clean_df,
        left_on="SP_deal",
        right_on="contract_number",
        how="inner",
    )
    if merged.empty:
        return merged

    merged = merged.drop_duplicates(subset=["SP_deal"], keep="first")
    merged["Дата расторжения"] = datetime.strptime(today_date, "%d-%m-%Y")
    merged["Дата расторжения (план)"] = datetime.strptime(today_date, "%d-%m-%Y")
    merged["Тип ФК"] = "Тип ФК"
    merged["Значение закрытия базисного актива"] = "Значение закрытия базисного актива"

    if "Notional" in merged.columns:
        merged["Notional"] = pd.to_numeric(merged["Notional"], errors="coerce")

    if "Initial_Date" in merged.columns:
        merged["Initial_Date"] = pd.to_datetime(merged["Initial_Date"], dayfirst=True, errors="coerce")

    rename_map = {
        "Initial_Date": "Дата заключения",
        "Notional": "Номинал контракта",
        "Currency": "Валюта номинала",
        "BA": "Базисный актив",
        "FSA": "Номер счета",
        "SP_deal": "Номер форвардного контракта",
        "contract_number": "№ соглашения о расторжении",
        "termination_amount": "Сумма к возврату",
        "currency": "Валюта возврата",
    }
    # Поле связанного кипрского контракта настраивается (MONGO_FIELD_CY),
    # но в выходном файле колонка всегда называется fc_num_on_CY_old.
    if cy_field and cy_field != DEFAULT_CY_FIELD and cy_field in merged.columns:
        rename_map[cy_field] = DEFAULT_CY_FIELD
    merged = merged.rename(columns=rename_map)

    merged = _ensure_columns(merged, FINAL_COLUMNS_DUBAI)
    merged = merged[FINAL_COLUMNS_DUBAI]
    merged = _normalize_output_types(merged)
    merged.insert(0, "№ п/п", merged.reset_index().index + 1)
    return merged


def build_trs_report(
    mongo_df_2: pd.DataFrame, clean_df: pd.DataFrame, today_date: str
) -> pd.DataFrame:
    if "Number" not in mongo_df_2.columns:
        return pd.DataFrame()

    merged = pd.merge(
        mongo_df_2,
        clean_df,
        left_on="Number",
        right_on="contract_number",
        how="inner",
    )
    if merged.empty:
        return merged

    merged = merged.drop_duplicates(subset=["Number"], keep="first")
    merged["Дата расторжения"] = datetime.strptime(today_date, "%d-%m-%Y")
    merged["Дата расторжения (план)"] = datetime.strptime(today_date, "%d-%m-%Y")
    merged["Тип ФК"] = "Тип ФК"
    merged["Значение закрытия базисного актива"] = "Значение закрытия базисного актива"

    if "Initial_Date" in merged.columns:
        merged["Initial_Date"] = pd.to_datetime(merged["Initial_Date"], dayfirst=True, errors="coerce")
    else:
        merged["Initial_Date"] = datetime.strptime(today_date, "%d-%m-%Y")

    if "Notional amount" in merged.columns:
        merged["Notional amount"] = pd.to_numeric(merged["Notional amount"], errors="coerce")

    merged = merged.rename(
        columns={
            "Initial_Date": "Дата заключения",
            "Notional amount": "Номинал контракта",
            "Currency": "Валюта номинала",
            "Underlying assets": "Базисный актив",
            "Agreement": "Номер счета",
            "Number": "Номер форвардного контракта",
            "contract_number": "№ соглашения о расторжении",
            "termination_amount": "Сумма к возврату",
            "currency": "Валюта возврата",
        }
    )

    merged = _ensure_columns(merged, FINAL_COLUMNS_TRS)
    merged = merged[FINAL_COLUMNS_TRS]
    merged = _normalize_output_types(merged)
    merged.insert(0, "№ п/п", merged.reset_index().index + 1)
    return merged
