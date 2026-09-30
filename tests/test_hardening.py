import uuid
from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from planning.cache import set_json
from planning.domain import PlanError, StationOccurrence
from planning.fuel import METRES_PER_MILE, solve
from planning.validation import validate_plan


@pytest.mark.parametrize(
    "body,content_type,status", [("{broken", "application/json", 400), ("text", "text/plain", 415)]
)
def test_parse_errors_have_safe_envelope(client, body, content_type, status):
    with patch("planning.views.build_plan") as planner:
        response = client.post("/api/v1/route-plan/", body, content_type=content_type)
    assert response.status_code == status
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert uuid.UUID(response.json()["request_id"])
    planner.assert_not_called()


def test_validator_rejects_tampering():
    node = StationOccurrence("1:0", "1", Decimal(400) * METRES_PER_MILE, Decimal(3))
    distance = Decimal(900) * METRES_PER_MILE
    purchase = solve([node], distance)[0]
    with pytest.raises(PlanError, match="validation"):
        validate_plan([node], [replace(purchase, gallons=purchase.gallons + 1)], distance)


def test_tiles_are_cached_and_do_not_expose_key(memory_cache, client, settings):
    settings.GEOAPIFY_API_KEY = "private-tile-key"
    token = uuid.uuid4()
    set_json("map:" + str(token), {"plan_id": str(token)})
    png = b"\x89PNG\r\n\x1a\nexample"
    real_client = httpx.Client
    requests = []

    def serve(request):
        requests.append(request)
        assert request.url.host == "maps.geoapify.com"
        return httpx.Response(200, content=png)

    with (
        patch(
            "planning.tiles.httpx.Client",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(serve), **kwargs
            ),
        ),
        patch("planning.planner.directions") as route,
    ):
        url = f"/map/{token}/tiles/5/7/12.png"
        first, second = client.get(url), client.get(url)
        assert first.content == second.content == png
        assert first["Content-Type"] == "image/png"
        assert "private-tile-key" not in str(first.headers)
        route.assert_not_called()
    assert len(requests) == 1
    assert client.get(f"/map/{token}/tiles/5/32/12.png").status_code == 404
    assert client.get(f"/map/{uuid.uuid4()}/tiles/5/7/12.png").status_code == 404
