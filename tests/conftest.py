from collections.abc import Iterator

import mongomock
import pytest


@pytest.fixture
def mongo_db() -> Iterator:
    client = mongomock.MongoClient()
    yield client["patient_records_test"]
    client.close()
