import io
import json
from unittest.mock import patch

import httpx
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from stations.enrichment import write_json
from stations.management.commands.enrich_stations import redact


def invoke(source, output, **options):
    text = io.StringIO()
    call_command("enrich_stations", str(source), output=str(output), stdout=text, **options)
    return text.getvalue()


def test_dry_run_and_ambiguous_submission_never_repeat(synthetic_source, tmp_path, settings):
    settings.BASE_DIR = tmp_path
    settings.GEOAPIFY_API_KEY = "private-key"
    source, _ = synthetic_source
    output = tmp_path / "out.json"
    with patch("stations.management.commands.enrich_stations.httpx.Client") as client:
        invoke(source, output)
        client.assert_not_called()
        client.return_value.__enter__.return_value.request.side_effect = httpx.ReadTimeout(
            "private-key"
        )
        with pytest.raises(CommandError, match="preserved job"):
            invoke(source, output, execute=True)
        assert client.return_value.__enter__.return_value.request.call_count == 1
    with patch("stations.management.commands.enrich_stations.httpx.Client") as client:
        with pytest.raises(CommandError, match="lost"):
            invoke(source, output, execute=True)
        client.assert_not_called()
    ledger = json.loads((tmp_path / "data/cache/enrichment/credit-ledger.json").read_text())
    assert ledger["reserved_credits"] == 0.5


def test_resume_completed_result_and_redaction(synthetic_source, tmp_path, settings):
    settings.BASE_DIR = tmp_path
    settings.GEOAPIFY_API_KEY = "private-key"
    source, _ = synthetic_source
    output = tmp_path / "out.json"
    description = json.loads(invoke(source, output))
    state_path = tmp_path / f"data/cache/enrichment/{description['cache_key']}.json"
    write_json(state_path, {"status": "pending", "job_id": "retained-job", "last_poll": 0})
    feature = {
        "country_code": "us",
        "state_code": "TX",
        "name": "Pilot",
        "store_ref": "1",
        "result_type": "amenity",
        "category": "service.vehicle.fuel",
        "lat": 35,
        "lon": -94,
        "unsafe_url": "https://example.com/?apiKey=private-key",
    }
    result = {"results": [{"id": "001", "result": {"results": [feature]}}]}
    with patch("stations.management.commands.enrich_stations.httpx.Client") as client:
        client.return_value.__enter__.return_value.request.return_value = httpx.Response(
            200, json=result
        )
        invoke(source, output, execute=True)
        args, kwargs = client.return_value.__enter__.return_value.request.call_args
        assert args[0] == "GET" and kwargs["params"]["id"] == "retained-job"
    assert "private-key" not in output.read_text() + state_path.read_text()
    assert json.loads(output.read_text())["records"][0]["status"] == "accepted"
    with patch("stations.management.commands.enrich_stations.httpx.Client") as client:
        invoke(source, output, execute=True)
        client.assert_not_called()
    assert redact({"apiKey": "private-key", "note": "private-key"}, "private-key") == {
        "note": "[REDACTED]"
    }
