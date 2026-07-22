import pandas as pd

from notes_app.terminations.analysis import build_analysis
from notes_app.terminations.excel_ingest import DISSOLUTION_MANUAL, DISSOLUTION_MSSP, IngestReport


def _clean_df(records):
    return pd.DataFrame(records)


def _report():
    return IngestReport(input_rows=1, output_rows=1)


def _deals(rows):
    return pd.DataFrame(rows)


def _empty():
    return pd.DataFrame()


def test_rate_is_computed_in_percent():
    clean = _clean_df([
        {"contract_number": "F1", "dissolution_type": DISSOLUTION_MSSP, "termination_amount": 15500.0,
         "currency": "CNY", "notional_amount": 15000000.0, "notional_currency": "CNY"},
    ])
    deals = _deals([{"SP_deal": "F1", "Notional": 15000000.0, "Currency": "CNY"}])

    payload = build_analysis(clean, _report(), deals, _empty())

    contract = payload["contracts"][0]
    assert contract["type"] == "dubai"
    assert round(contract["rate_pct"], 4) == round(15500.0 / 15000000.0 * 100.0, 4)
    assert contract["notional_mismatch"] is False
    assert payload["can_generate"] is True


def test_cyprus_contract_raises_alert():
    clean = _clean_df([
        {"contract_number": "F1", "dissolution_type": DISSOLUTION_MANUAL, "termination_amount": 100.0,
         "currency": "USD", "notional_amount": 1000.0, "notional_currency": "USD"},
    ])
    deals = _deals([{"SP_deal": "F1", "Notional": 1000.0, "Currency": "USD", "fc_num_on_CY_old": "CY-OLD-9"}])

    payload = build_analysis(clean, _report(), deals, _empty())

    assert payload["contracts"][0]["cyprus"] is True
    assert payload["contracts"][0]["cyprus_value"] == "CY-OLD-9"
    assert payload["summary"]["cyprus_count"] == 1
    assert any(issue["code"] == "cyprus_contract" for issue in payload["alerts"])


def test_notional_mismatch_flagged():
    clean = _clean_df([
        {"contract_number": "F1", "dissolution_type": DISSOLUTION_MANUAL, "termination_amount": 100.0,
         "currency": "USD", "notional_amount": 1000.0, "notional_currency": "USD"},
    ])
    deals = _deals([{"SP_deal": "F1", "Notional": 900.0, "Currency": "USD"}])

    payload = build_analysis(clean, _report(), deals, _empty())

    assert payload["contracts"][0]["notional_mismatch"] is True
    assert payload["summary"]["notional_mismatches"] == 1
    assert any(issue["code"] == "notional_mismatch" for issue in payload["warnings"])


def test_not_found_contract_does_not_block_when_others_exist():
    clean = _clean_df([
        {"contract_number": "F1", "dissolution_type": DISSOLUTION_MANUAL, "termination_amount": 100.0,
         "currency": "USD", "notional_amount": 1000.0, "notional_currency": "USD"},
        {"contract_number": "F404", "dissolution_type": DISSOLUTION_MSSP, "termination_amount": 50.0,
         "currency": "USD", "notional_amount": 500.0, "notional_currency": "USD"},
    ])
    deals = _deals([{"SP_deal": "F1", "Notional": 1000.0, "Currency": "USD"}])

    payload = build_analysis(clean, _report(), deals, _empty())

    assert payload["summary"]["not_found"] == ["F404"]
    assert payload["can_generate"] is True
    assert any(issue["code"] == "not_found" for issue in payload["warnings"])


def test_dissolution_type_split_in_dubai_summary():
    clean = _clean_df([
        {"contract_number": "F1", "dissolution_type": DISSOLUTION_MANUAL, "termination_amount": 100.0,
         "currency": "USD", "notional_amount": 1000.0, "notional_currency": "USD"},
        {"contract_number": "F2", "dissolution_type": DISSOLUTION_MANUAL, "termination_amount": 100.0,
         "currency": "USD", "notional_amount": 1000.0, "notional_currency": "USD"},
        {"contract_number": "F3", "dissolution_type": DISSOLUTION_MSSP, "termination_amount": 100.0,
         "currency": "USD", "notional_amount": 1000.0, "notional_currency": "USD"},
    ])
    deals = _deals([
        {"SP_deal": "F1", "Notional": 1000.0, "Currency": "USD"},
        {"SP_deal": "F2", "Notional": 1000.0, "Currency": "USD"},
        {"SP_deal": "F3", "Notional": 1000.0, "Currency": "USD"},
    ])

    payload = build_analysis(clean, _report(), deals, _empty())

    assert payload["summary"]["dubai"] == {"total": 3, "manual": 2, "mssp": 1, "unknown": 0}
    assert payload["summary"]["trs"] is None


def test_nothing_found_blocks_generation():
    clean = _clean_df([
        {"contract_number": "F404", "dissolution_type": DISSOLUTION_MSSP, "termination_amount": 50.0,
         "currency": "USD", "notional_amount": 500.0, "notional_currency": "USD"},
    ])

    payload = build_analysis(clean, _report(), _empty(), _empty())

    assert payload["can_generate"] is False
    assert any(issue["code"] == "no_found_contracts" for issue in payload["errors"])
