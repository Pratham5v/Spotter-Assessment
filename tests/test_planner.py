from decimal import Decimal
from unittest.mock import patch

import pytest

from planning.domain import PlanError, StationOccurrence
from planning.fuel import METRES_PER_MILE
from planning.planner import build_plan


def candidate(template, identifier, miles, price):
    station = dict(
        template,
        opis_id=identifier,
        price=Decimal(price),
        min_price=Decimal(price),
        max_price=Decimal(price),
    )
    return {
        "station": station,
        "offset_m": 0,
        "occurrence": StationOccurrence(
            identifier + ":0", identifier, Decimal(miles) * METRES_PER_MILE, Decimal(price)
        ),
    }


def routing_script(legs_by_call, calls):
    def route(points, radiuses, budget):
        budget.consume()
        legs = [str(Decimal(m) * METRES_PER_MILE) for m in legs_by_call[len(calls)]]
        calls.append(points)
        assert len(legs) == len(points) - 1
        return {
            "geometry": {"type": "LineString", "coordinates": points},
            "distance_m": str(sum(map(Decimal, legs))),
            "duration_seconds": 100,
            "legs_m": legs,
            "snapped": points,
            "snap_distances_m": [0] * len(points),
            "warnings": [],
        }

    return route


def run(active_dataset, legs):
    station = active_dataset.stations.values().get()
    candidates = [
        candidate(station, "bridge", 250, 5),
        candidate(station, "first", 450, 4),
        candidate(station, "cheap", 750, 2),
    ]
    calls = []
    with (
        patch("planning.planner.validate_endpoint", return_value="synthetic"),
        patch("planning.planner.geometry.candidates", return_value=candidates),
        patch("planning.planner.directions", side_effect=routing_script(legs, calls)),
    ):
        result = build_plan([-100, 35], [-85, 35])
    return result, calls


def test_actual_gap_uses_one_bounded_repair(active_dataset, memory_cache):
    result, calls = run(active_dataset, [[1000], [510, 300, 250], [250, 260, 300, 250]])
    assert len(calls) == result["diagnostics"]["routing_attempts_this_request"] == 3
    assert result["diagnostics"]["repair_used"]
    assert [s["station_id"] for s in result["visited_stations"]] == ["bridge", "first", "cheap"]
    assert result["fuel"]["purchased_gallons"] == "56.000000000000"
    assert result["fuel"]["total_cost_usd"] == "175.00"


def test_failed_repair_never_uses_fourth_route(active_dataset, memory_cache):
    with pytest.raises(PlanError) as failure:
        run(active_dataset, [[1000], [510, 300, 250], [510, 260, 300, 250]])
    assert failure.value.code == "NO_VERIFIED_PLAN"


def test_final_zero_purchase_waypoint_stays_on_map(active_dataset, memory_cache):
    result, calls = run(active_dataset, [[1000], [200, 200, 500]])
    assert len(calls) == 2
    assert len(result["visited_stations"]) == 2 and len(result["fuel_stops"]) == 1
    assert result["visited_stations"][0]["purchased_here"] is False
    assert result["fuel_stops"][0]["station_id"] == "cheap"
    assert result["fuel"]["total_cost_usd"] == "80.00"
