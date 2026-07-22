import pytest
from openpyxl import Workbook


TERMINATION_REPORT_HEADERS = [
    "Status",
    "Date of early termination",
    "Contract number",
    "Notional amount",
    "CUR of notional amount",
    "Quote",
    "Invested amount",
    "CUR of invested amount",
    "Early termination amount",
    "CUR of early termination amount",
]


@pytest.fixture
def temp_data(tmp_path, monkeypatch):
    """Изолирует настройки и историю расторжений на время теста."""
    monkeypatch.setattr(
        "notes_app.terminations.config.SETTINGS_PATH", tmp_path / "settings.json"
    )
    monkeypatch.setattr(
        "notes_app.terminations.database.DATABASE_PATH", tmp_path / "test.sqlite3"
    )
    monkeypatch.setattr(
        "notes_app.database.DATABASE_PATH", tmp_path / "noteflow.sqlite3"
    )
    from notes_app.terminations.database import initialize_database

    initialize_database()
    return tmp_path


@pytest.fixture
def make_report():
    """Фабрика тестовых Excel-файлов расторжений."""

    def _make(
        path,
        contract="F1",
        term_date="17.07.2026",
        status="Created",
        amount="1000,00",
    ):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(TERMINATION_REPORT_HEADERS)
        worksheet.append(
            [
                status,
                term_date,
                contract,
                "1 000 000,00",
                "USD",
                "1,0",
                "1000",
                "USD",
                amount,
                "USD",
            ]
        )
        workbook.save(path)
        return path

    return _make
