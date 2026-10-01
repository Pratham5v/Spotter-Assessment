import json

import pytest

from stations.importing import import_snapshot
from stations.ingestion import audit_csv
from tests.test_ingestion import row, source


@pytest.fixture
def synthetic_source(tmp_path):
    path = source(tmp_path, [row("3"), row("5"), row("3", "ON")])
    audit = audit_csv(path)
    artifact = tmp_path / "enriched.json"
    artifact.write_text(
        json.dumps(
            {
                "source_sha256": audit.sha256,
                "version": "synthetic_v1",
                "records": [
                    {
                        "opis_id": "001",
                        "fingerprint": audit.stations["001"]["fingerprint"],
                        "status": "accepted",
                        "latitude": 32.4446053,
                        "longitude": -93.9794675,
                        "source": "synthetic",
                        "evidence": {
                            "identity_reason": "authored test fixture",
                            "retrieved_at": "2000-01-01T00:00:00Z",
                        },
                    }
                ],
            }
        )
    )
    return path, artifact


@pytest.fixture
def active_dataset(db, synthetic_source):
    return import_snapshot(*synthetic_source)[0]


@pytest.fixture
def memory_cache(settings):
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests"}
    }
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
