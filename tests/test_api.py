import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest

from planning.cache import set_json
from planning.domain import StationOccurrence
from planning.fuel import METRES_PER_MILE
from planning.planner import build_plan

REQUEST = {
    "start": {"latitude": 32.777, "longitude": -96.797},
    "finish": {"latitude": 33.749, "longitude": -84.388},
}


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(extra=1),
        lambda r: r["start"].update(latitude=True),
        lambda r: r["finish"].update(longitude="-84"),
        lambda r: r["finish"].update(latitude=100),
    ],
)
def test_invalid_inputs_do_not_route(client, change):
    import copy

    request = copy.deepcopy(REQUEST)
    change(request)
    with patch("planning.views.build_plan") as planner:
        response = client.post("/api/v1/route-plan/", request, content_type="application/json")
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_INPUT"
    planner.assert_not_called()


def fake_directions(points, radiuses, budget):
    budget.consume()
    legs = (
        [str(Decimal(900) * METRES_PER_MILE)]
        if len(points) == 2
        else [str(Decimal(400) * METRES_PER_MILE), str(Decimal(500) * METRES_PER_MILE)]
    )
    return {
        "geometry": {"type": "LineString", "coordinates": points},
        "distance_m": str(sum(map(Decimal, legs))),
        "duration_seconds": 100,
        "legs_m": legs,
        "snapped": points,
        "snap_distances_m": [0] * len(points),
        "warnings": [],
    }


def test_full_plan_map_and_cache_are_consistent(active_dataset, memory_cache, client):
    station = active_dataset.stations.values().get()
    station["name"] = "<script>alert(1)</script>"
    candidate = {
        "occurrence": StationOccurrence(
            "001:0", "001", Decimal(400) * METRES_PER_MILE, station["price"]
        ),
        "station": station,
        "offset_m": 0,
    }
    with (
        patch("planning.planner.validate_endpoint", return_value="test-boundary"),
        patch("planning.planner.directions", side_effect=fake_directions),
        patch("planning.planner.geometry.candidates", return_value=[candidate]),
    ):
        response = client.post("/api/v1/route-plan/", REQUEST, content_type="application/json")
        assert response.status_code == 200
        result = response.json()
        assert result["fuel"]["purchased_gallons"] == "40.000000000000"
        assert result["fuel"]["total_cost_usd"] == "160.00"
        assert result["diagnostics"]["routing_attempts_this_request"] == 2
        cached = client.post("/api/v1/route-plan/", REQUEST, content_type="application/json").json()
        assert cached["diagnostics"]["routing_attempts_this_request"] == 0
        assert cached["diagnostics"]["plan_cache_hit"]
    with patch("planning.views.build_plan") as planner:
        page = client.get(result["map_url"])
        assert page.status_code == 200
        assert b"<script>alert(1)</script>" not in page.content
        assert b"&lt;script&gt;" in page.content
        planner.assert_not_called()


def test_zero_trip_uses_no_provider(active_dataset, memory_cache):
    with (
        patch("planning.planner.validate_endpoint", return_value="test"),
        patch("planning.planner.directions") as route,
    ):
        result = build_plan([-96.797, 32.777], [-96.797, 32.777])
        assert result["route"]["geometry"]["type"] == "Point"
        assert result["fuel"]["remaining_gallons"] == "50.000000000000"
        route.assert_not_called()


def test_map_expiry(client, memory_cache):
    assert client.get(f"/map/{uuid.uuid4()}/").status_code == 404


def test_cache_schema_remains_json(memory_cache):
    from django.core.cache import cache

    set_json("test", {"price": "3"})
    assert isinstance(cache.get("test"), str)
