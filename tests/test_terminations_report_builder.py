from datetime import datetime

import pandas as pd

from notes_app.terminations.report_builder import (
    FINAL_COLUMNS_DUBAI,
    FINAL_COLUMNS_TRS,
    build_dubai_report,
    build_trs_report,
    missing_contracts,
)


def _clean_df(contract="F1", currency="CNY", amount=15500.0):
    return pd.DataFrame(
        {
            "contract_number": [contract],
            "currency": [currency],
            "termination_amount": [amount],
            "notional_amount": [15000000.0],
        }
    )


def test_dubai_report_columns_and_cy_field():
    mongo_df = pd.DataFrame(
        {
            "SP_deal": ["F1"],
            "Initial_Date": [datetime(2024, 1, 10)],
            "Notional": [15000000],
            "Currency": ["CNY"],
            "BA": ["AAPL US"],
            "FSA": ["ACC-1"],
            "fc_num_on_CY_old": ["CY-OLD-99"],
        }
    )

    report = build_dubai_report(mongo_df, _clean_df(), "17-07-2026")

    assert list(report.columns) == ["№ п/п"] + FINAL_COLUMNS_DUBAI
    assert report.iloc[0]["fc_num_on_CY_old"] == "CY-OLD-99"
    assert report.iloc[0]["Сумма к возврату"] == 15500.0
    assert pd.api.types.is_datetime64_any_dtype(report["Дата расторжения"])


def test_dubai_report_renames_custom_cy_field():
    mongo_df = pd.DataFrame(
        {
            "SP_deal": ["F1"],
            "Initial_Date": [datetime(2024, 1, 10)],
            "Notional": [15000000],
            "Currency": ["CNY"],
            "cyprus_link": ["CY-OLD-42"],
        }
    )

    report = build_dubai_report(mongo_df, _clean_df(), "17-07-2026", cy_field="cyprus_link")

    assert report.iloc[0]["fc_num_on_CY_old"] == "CY-OLD-42"


def test_trs_report_basic():
    mongo_df = pd.DataFrame(
        {
            "Number": ["F2"],
            "Initial_Date": [datetime(2024, 2, 1)],
            "Notional amount": [30000000],
            "Currency": ["CNY"],
            "Underlying assets": ["TSLA US"],
            "Agreement": ["ACC-2"],
        }
    )

    report = build_trs_report(mongo_df, _clean_df(contract="F2", amount=3000.0), "17-07-2026")

    assert list(report.columns) == ["№ п/п"] + FINAL_COLUMNS_TRS
    assert report.iloc[0]["Номер форвардного контракта"] == "F2"
    assert report.iloc[0]["Сумма к возврату"] == 3000.0


def test_missing_contracts_detects_absent():
    mongo_df_1 = pd.DataFrame({"SP_deal": ["F1"]})
    mongo_df_2 = pd.DataFrame({"Number": ["F2"]})

    assert missing_contracts(["F1", "F2", "F3"], mongo_df_1, mongo_df_2) == ["F3"]
    assert missing_contracts(["F1"], mongo_df_1, mongo_df_2) == []
