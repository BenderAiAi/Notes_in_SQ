import pytest
from pymongo.errors import OperationFailure

from notes_app.terminations.mongo_client import _find_contracts


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
