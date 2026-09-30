import io
import json

from django.core.management import call_command

from stations.models import DatasetImport


def test_synthetic_demo_preserves_active_snapshot(active_dataset):
    output = io.StringIO()
    call_command("demo_plan", stdout=output)
    result = json.loads(output.getvalue())
    assert result["demonstration"]["synthetic"]
    assert result["demonstration"]["actual_external_requests"] == 0
    assert result["fuel"]["purchased_gallons"] == "40.000000000000"
    assert result["fuel"]["total_cost_usd"] == "160.00"
    assert DatasetImport.objects.count() == 1
    assert DatasetImport.objects.get(is_active=True).id == active_dataset.id
