import json
from decimal import Decimal
from unittest.mock import Mock, patch

import httpx
import pytest

from planning.domain import PlanError
from planning.fuel import METRES_PER_MILE
from planning.planner import build_plan
from planning.providers.ors import RoutingBudget, directions
from tests.test_planner import candidate
from tests.test_provider import POINTS, response


@pytest.mark.parametrize(
    "legs,error_code",
    [
        ([[1000], [450, 300, 250]], None),
        ([[1000], [510, 300, 250], [250, 260, 300, 250]], None),
        ([[1000], [510, 300, 250], [510, 260, 300, 250]], "NO_VERIFIED_PLAN"),
    ],
)
def test_plan_shares_one_client_through_final_routing_and_repair(
    active_dataset, memory_cache, settings, legs, error_code
):
    settings.ORS_API_KEY = "test"
    station = active_dataset.stations.values().get()
    found = [
        candidate(station, "bridge", 250, 5),
        candidate(station, "first", 450, 4),
        candidate(station, "cheap", 750, 2),
    ]
    requests, clients = [], []
    real_client = httpx.Client

    def handler(request):
        payload = json.loads(request.content)
        distances = [float(Decimal(m) * METRES_PER_MILE) for m in legs[len(requests)]]
        requests.append(payload)
        points = payload["coordinates"]
        assert payload["instructions"] is True
        assert payload["options"] == {"avoid_borders": "all", "vehicle_type": "hgv"}
        assert payload["radiuses"] == [350, *([100] * (len(points) - 2)), 350]
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "geometry": {"type": "LineString", "coordinates": points},
                        "properties": {
                            "summary": {"distance": sum(distances), "duration": 100},
                            "segments": [{"distance": d} for d in distances],
                            "way_points": list(range(len(points))),
                        },
                    }
                ]
            },
        )

    def factory(**kwargs):
        client = real_client(transport=httpx.MockTransport(handler), **kwargs)
        client.close = Mock(wraps=client.close)
        clients.append(client)
        return client

    with (
        patch("planning.planner.validate_endpoint", return_value="synthetic"),
        patch("planning.planner.geometry.candidates", return_value=found),
        patch("planning.providers.ors.validate_geometry"),
        patch("planning.providers.ors.httpx.Client", side_effect=factory),
    ):
        if error_code:
            with pytest.raises(PlanError) as failure:
                build_plan([-100, 35], [-85, 35])
            assert failure.value.code == error_code
        else:
            plan = build_plan([-100, 35], [-85, 35])
            assert plan["diagnostics"]["routing_attempts_this_request"] == len(legs)
            # A saved-plan hit does not construct a second client.
            assert build_plan([-100, 35], [-85, 35])["diagnostics"]["plan_cache_hit"]
    assert len(requests) == len(legs) <= 3
    assert len(clients) == 1 and clients[0].is_closed
    clients[0].close.assert_called_once()


@pytest.mark.parametrize("retry_kind", ["timeout", "server_error"])
def test_retries_reuse_client_and_recalculate_remaining_time(memory_cache, settings, retry_kind):
    settings.ORS_API_KEY = "test"
    clock = [100.0]
    budgets = []
    clients = []
    real_client = httpx.Client

    def handler(request):
        budgets.append(request.extensions["timeout"])
        if len(budgets) == 1:
            clock[0] += 32
            if retry_kind == "timeout":
                raise httpx.ReadTimeout("private URL", request=request)
            return httpx.Response(500)
        body = response()
        body["features"][0]["geometry"]["coordinates"] = json.loads(request.content)["coordinates"]
        return httpx.Response(200, json=body)

    def factory(**kwargs):
        client = real_client(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    with (
        patch("planning.providers.ors.time.monotonic", side_effect=lambda: clock[0]),
        patch("planning.providers.ors.validate_geometry"),
        patch("planning.providers.ors.httpx.Client", side_effect=factory),
        RoutingBudget(started=100) as budget,
    ):
        directions(POINTS, [350, 350], budget)
        clock[0] += 2
        directions(POINTS[::-1], [350, 350], budget)
        with pytest.raises(PlanError) as exhausted:
            directions([POINTS[0], [-97.2, 32.75]], [350, 350], budget)
        assert exhausted.value.code == "NO_VERIFIED_PLAN"
    assert len(clients) == 1 and clients[0].is_closed
    assert len(budgets) == budget.attempts == 3
    assert [b["read"] for b in budgets] == [15, 3, 1]
    assert [b["connect"] for b in budgets] == [5, 3, 1]
    assert all(b["write"] == b["read"] == b["pool"] for b in budgets)


@pytest.mark.parametrize("failure", ["auth", "invalid_body", "oversized", "deadline", "connection"])
def test_client_closes_on_provider_errors(memory_cache, settings, failure):
    settings.ORS_API_KEY = "test-private-key"
    clock = [100.0]
    clients = []
    real_client = httpx.Client

    def handler(request):
        if failure == "connection":
            raise httpx.ConnectError("test-private-key", request=request)
        if failure == "auth":
            return httpx.Response(401, content=b"test-private-key")
        if failure == "invalid_body":
            return httpx.Response(200, content=b"test-private-key")
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * 12_000_001)
        clock[0] = 135
        return httpx.Response(200, json=response())

    def factory(**kwargs):
        client = real_client(transport=httpx.MockTransport(handler), **kwargs)
        client.close = Mock(wraps=client.close)
        clients.append(client)
        return client

    expected = {
        "auth": "PROVIDER_UNAVAILABLE",
        "connection": "PROVIDER_UNAVAILABLE",
        "invalid_body": "INVALID_PROVIDER_RESPONSE",
        "oversized": "INVALID_PROVIDER_RESPONSE",
        "deadline": "PROVIDER_TIMEOUT",
    }
    with (
        patch("planning.providers.ors.time.monotonic", side_effect=lambda: clock[0]),
        patch("planning.providers.ors.httpx.Client", side_effect=factory),
    ):
        with pytest.raises(PlanError) as failure_error, RoutingBudget(started=100) as budget:
            directions(POINTS, [350, 350], budget)
    assert failure_error.value.code == expected[failure]
    assert "test-private-key" not in str(failure_error.value)
    assert budget.attempts == 1
    assert len(clients) == 1 and clients[0].is_closed
    clients[0].close.assert_called_once()


def test_expired_budget_and_zero_distance_do_not_construct_client(
    active_dataset, memory_cache, settings
):
    settings.ORS_API_KEY = "test"
    with (
        patch("planning.providers.ors.httpx.Client") as client,
        patch("planning.providers.ors.time.monotonic", return_value=135),
        patch("planning.planner.validate_endpoint", return_value="synthetic"),
    ):
        with RoutingBudget(started=100) as budget, pytest.raises(PlanError) as failure:
            directions(POINTS, [350, 350], budget)
        assert failure.value.code == "NO_VERIFIED_PLAN"
        assert budget.attempts == 0
        assert (
            build_plan([-100, 35], [-100, 35])["diagnostics"]["routing_attempts_this_request"] == 0
        )
    client.assert_not_called()
