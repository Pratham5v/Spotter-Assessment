from unittest.mock import patch

import httpx
import pytest

from planning.domain import PlanError
from planning.providers.ors import RoutingBudget, directions, normalize_response

POINTS = [[-96.797, 32.777], [-97.3308, 32.7555]]


def response():
    return {
        "features": [
            {
                "geometry": {"type": "LineString", "coordinates": POINTS},
                "properties": {
                    "summary": {"distance": 51716.5, "duration": 3500},
                    "segments": [{"distance": 51716.5}],
                    "way_points": [0, 1],
                },
            }
        ]
    }


def test_provider_leg_and_geography_contract():
    with patch("planning.providers.ors.validate_geometry"):
        assert normalize_response(response(), POINTS, [350, 350])["legs_m"] == ["51716.5"]
        bad = response()
        bad["features"][0]["properties"].pop("segments")
        with pytest.raises(PlanError, match="inconsistent"):
            normalize_response(bad, POINTS, [350, 350])
        bad = response()
        bad["features"][0]["properties"]["segments"][0]["distance"] = 0
        with pytest.raises(PlanError):
            normalize_response(bad, POINTS, [350, 350])


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "PROVIDER_UNAVAILABLE"),
        (403, "PROVIDER_UNAVAILABLE"),
        (429, "PROVIDER_QUOTA_EXCEEDED"),
        (404, "ROUTE_NOT_FOUND"),
        (500, "PROVIDER_UNAVAILABLE"),
    ],
)
def test_http_failures_are_safe_and_budgeted(memory_cache, settings, status, code):
    settings.ORS_API_KEY = "test-private-key"
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"unsafe": "test-private-key"})
    )
    budget = RoutingBudget()
    with patch(
        "planning.providers.ors.httpx.Client",
        side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
    ):
        with pytest.raises(PlanError) as caught:
            directions(POINTS, [350, 350], budget)
    assert caught.value.code == code
    assert "test-private-key" not in str(caught.value)
    assert budget.attempts == (2 if status == 500 else 1)


def test_timeout_retry_cannot_become_a_fourth_attempt(memory_cache, settings):
    settings.ORS_API_KEY = "test"
    real_client = httpx.Client

    def timeout(request):
        raise httpx.ReadTimeout("private provider URL", request=request)

    budget = RoutingBudget(attempts=2)
    with patch(
        "planning.providers.ors.httpx.Client",
        side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(timeout), **kwargs),
    ):
        with pytest.raises(PlanError) as caught:
            directions(POINTS, [350, 350], budget)
    assert budget.attempts == 3 and caught.value.code == "PROVIDER_TIMEOUT"
    with pytest.raises(PlanError):
        budget.consume()


def test_route_cache_requires_no_outbound_call(memory_cache, settings):
    settings.ORS_API_KEY = "test"
    real_client = httpx.Client
    with (
        patch("planning.providers.ors.validate_geometry"),
        patch(
            "planning.providers.ors.httpx.Client",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response())),
                **kwargs,
            ),
        ),
    ):
        first, second = RoutingBudget(), RoutingBudget()
        assert directions(POINTS, [350, 350], first) == directions(POINTS, [350, 350], second)
    assert first.attempts == 1 and second.attempts == 0 and second.cache_hits == 1
