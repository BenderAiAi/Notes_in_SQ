import pytest
from pymongo.errors import OperationFailure

from notes_app.terminations.mongo_client import _find_contracts, load_mongo_settings


class UnauthorizedCollection:
    def find(self, _query):
        raise OperationFailure("not authorized", code=13)


def test_unauthorized_query_has_short_safe_message() -> None:
    with pytest.raises(RuntimeError) as error:
        _find_contracts(
            UnauthorizedCollection(),
            "Number",
            ["123", "456"],
            "TRS_deals.trs",
        )

    assert "TRS_deals.trs" in str(error.value)
    assert "нет права find" in str(error.value)
    assert "123" not in str(error.value)


def test_default_trs_collection_matches_working_mongo_layout(monkeypatch) -> None:
    monkeypatch.setenv("MONGO_URI", "mongodb://example.test:27017/")
    monkeypatch.delenv("MONGO_COLLECTION_TRS", raising=False)

    settings = load_mongo_settings()

    assert settings.trs_db == "TRS_deals"
    assert settings.trs_collection == "dubai"
