from notes_app.terminations.database import (
    history_summary,
    list_history,
    record_terminations,
)


def _entry(contract="F1", term_date="2026-07-17", rate=0.1, amount=15500.0, currency="CNY"):
    return {
        "contract_number": contract,
        "termination_date": term_date,
        "contract_type": "dubai",
        "rate_pct": rate,
        "termination_amount": amount,
        "return_currency": currency,
        "notional": 15000000.0,
        "notional_currency": currency,
        "dissolution_type": "manual",
        "cyprus_flag": False,
        "source_file": "term.xlsx",
    }


def test_record_creates_then_upserts(temp_data):
    created, updated = record_terminations([_entry(rate=0.1, amount=15500.0)])
    assert (created, updated) == (1, 0)

    # Повтор того же контракта и даты обновляет запись, а не плодит дубль.
    created, updated = record_terminations([_entry(rate=0.2, amount=30000.0)])
    assert (created, updated) == (0, 1)

    rows = list_history()
    assert len(rows) == 1
    assert rows[0]["termination_amount"] == 30000.0
    assert rows[0]["rate_pct"] == 0.2


def test_same_contract_different_date_is_new_row(temp_data):
    record_terminations([_entry(term_date="2026-07-17")])
    created, updated = record_terminations([_entry(term_date="2026-08-01")])
    assert (created, updated) == (1, 0)
    assert len(list_history()) == 2


def test_list_history_filters(temp_data):
    record_terminations([
        _entry(contract="F1", currency="CNY"),
        _entry(contract="F2", term_date="2026-07-18", currency="USD"),
    ])

    assert [row["contract_number"] for row in list_history(search="F2")] == ["F2"]
    assert [row["contract_number"] for row in list_history(currency="usd")] == ["F2"]
    assert len(list_history(date_from="2026-07-18")) == 1


def test_history_summary_totals(temp_data):
    record_terminations([
        _entry(contract="F1", currency="CNY", amount=15500.0),
        _entry(contract="F2", term_date="2026-07-18", currency="CNY", amount=3000.0),
    ])
    summary = history_summary()
    assert summary["total"] == 2
    cny = next(row for row in summary["by_currency"] if row["currency"] == "CNY")
    assert cny["termination_sum"] == 18500.0
    assert cny["count"] == 2
