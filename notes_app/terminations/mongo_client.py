from __future__ import annotations

import os
from dataclasses import dataclass

import pandas as pd
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import OperationFailure


@dataclass(frozen=True)
class MongoSettings:
    uri: str
    deals_db: str
    deals_collection: str
    trs_db: str
    trs_collection: str
    timeout_ms: int
    cy_field: str


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Не задана обязательная переменная окружения: {name}")
    return value


def load_mongo_settings() -> MongoSettings:
    return MongoSettings(
        uri=_required_env("MONGO_URI"),
        deals_db=os.getenv("MONGO_DB_DEALS", "deals_log"),
        deals_collection=os.getenv("MONGO_COLLECTION_DEALS", "dubai"),
        trs_db=os.getenv("MONGO_DB_TRS", "TRS_deals"),
        trs_collection=os.getenv("MONGO_COLLECTION_TRS", "dubai"),
        timeout_ms=int(os.getenv("MONGO_TIMEOUT_MS", "7000")),
        cy_field=os.getenv("MONGO_FIELD_CY", "fc_num_on_CY_old"),
    )


def get_client(settings: MongoSettings) -> MongoClient:
    return MongoClient(settings.uri, serverSelectionTimeoutMS=settings.timeout_ms)


def get_collections(client: MongoClient, settings: MongoSettings) -> tuple[Collection, Collection]:
    deals_collection = client[settings.deals_db][settings.deals_collection]
    trs_collection = client[settings.trs_db][settings.trs_collection]
    return deals_collection, trs_collection


def fetch_contract_data(
    client: MongoClient,
    settings: MongoSettings,
    contract_numbers: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    deals_collection, trs_collection = get_collections(client, settings)

    deals_rows = _find_contracts(
        deals_collection,
        "SP_deal",
        contract_numbers,
        f"{settings.deals_db}.{settings.deals_collection}",
    )
    trs_rows = _find_contracts(
        trs_collection,
        "Number",
        contract_numbers,
        f"{settings.trs_db}.{settings.trs_collection}",
    )
    return pd.DataFrame(deals_rows), pd.DataFrame(trs_rows)


def _find_contracts(
    collection: Collection,
    field: str,
    contract_numbers: list[str],
    namespace: str,
) -> list[dict]:
    try:
        return list(collection.find({field: {"$in": contract_numbers}}))
    except OperationFailure as exc:
        if exc.code == 13:
            raise RuntimeError(
                f"MongoDB отклонила чтение {namespace}: у пользователя из MONGO_URI "
                "нет права find для этой коллекции."
            ) from None
        raise
