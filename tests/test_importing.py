import json

import pytest

from stations.importing import import_snapshot
from stations.ingestion import AuditError
from stations.models import DatasetImport, PriceObservation, Station

pytestmark = pytest.mark.django_db


def test_atomic_import_idempotence_and_provenance(synthetic_source):
    dataset, created = import_snapshot(*synthetic_source)
    assert created and dataset.is_active
    again, created = import_snapshot(*synthetic_source)
    assert not created and again.id == dataset.id
    assert Station.objects.count() == 1
    assert PriceObservation.objects.count() == 3
    assert PriceObservation.objects.filter(classification="CA", station__isnull=True).count() == 1
    artifact = synthetic_source[1]
    data = json.loads(artifact.read_text())
    data["version"] = "synthetic_v2"
    artifact.write_text(json.dumps(data))
    replacement, created = import_snapshot(*synthetic_source)
    assert created and replacement.id != dataset.id
    assert DatasetImport.objects.filter(is_active=True).count() == 1
    dataset.refresh_from_db()
    assert not dataset.is_active


def test_stale_failed_import_preserves_active_snapshot(synthetic_source):
    dataset, _ = import_snapshot(*synthetic_source)
    artifact = synthetic_source[1]
    data = json.loads(artifact.read_text())
    data["records"][0]["fingerprint"] = "changed"
    artifact.write_text(json.dumps(data))
    with pytest.raises(AuditError, match="Stale"):
        import_snapshot(*synthetic_source)
    assert DatasetImport.objects.get(is_active=True).id == dataset.id


def test_coordinate_provenance_required(synthetic_source):
    artifact = synthetic_source[1]
    data = json.loads(artifact.read_text())
    data["records"][0]["evidence"] = {}
    artifact.write_text(json.dumps(data))
    with pytest.raises(AuditError, match="provenance"):
        import_snapshot(*synthetic_source)
