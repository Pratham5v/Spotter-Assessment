from decimal import Decimal as D
from random import Random

import pytest

from planning.domain import PlanError, StationOccurrence
from planning.fuel import METRES_PER_MILE, solve
from planning.validation import validate_plan


def nodes(pairs):
    return [
        StationOccurrence(str(i), str(i), D(str(mile)) * METRES_PER_MILE, D(str(price)))
        for i, (mile, price) in enumerate(pairs)
    ]


@pytest.mark.parametrize(
    "distance,pairs,cost",
    [
        (0, [], "0"),
        (100, [], "0"),
        (500, [], "0"),
        (900, [(400, 3), (700, 5)], "120"),
        (900, [(400, 5), (600, 3)], "140"),
        (1000, [(500, 4), (509, 3)], "150.90"),
        (700, [("499.96", 4), ("500.04", 3)], "60.004"),
    ],
)
def test_boundaries_and_partial_fills(distance, pairs, cost):
    occurrences = nodes(pairs)
    distance_m = D(distance) * METRES_PER_MILE
    result = solve(occurrences, distance_m)
    totals = validate_plan(occurrences, result, distance_m)
    assert abs(totals["cost"] - D(cost)) < D("1e-20")
    if distance == 1000:
        assert len(result) == 2


def test_just_past_range_is_unreachable():
    with pytest.raises(PlanError):
        solve(nodes([("500.000001", 3)]), D(700) * METRES_PER_MILE)


def exhaustive(stations, distance, capacity):
    states, previous = {capacity: 0}, 0
    for position, price in sorted(stations):
        updated = {}
        for fuel, cost in states.items():
            arrival = fuel - position + previous
            if arrival < 0:
                continue
            for buy in range(capacity - arrival + 1):
                departure = arrival + buy
                updated[departure] = min(updated.get(departure, float("inf")), cost + buy * price)
        states, previous = updated, position
    return min((cost for fuel, cost in states.items() if fuel >= distance - previous), default=None)


def test_decimal_solver_against_independent_exhaustive_oracle():
    random = Random(20260930)
    for _ in range(2000):
        # One grid unit = 50 miles = 5 gallons. Includes equal/coincident stations.
        distance = random.randrange(0, 31)
        pairs = [
            (random.randrange(distance + 1), random.randrange(1, 8))
            for _ in range(random.randrange(9))
        ]
        pairs = [(x, p) for x, p in pairs if x < distance]
        expected = exhaustive(pairs, distance, 10)
        occurrences = nodes([(x * 50, p) for x, p in pairs])
        distance_m = D(distance * 50) * METRES_PER_MILE
        try:
            purchases = solve(occurrences, distance_m)
        except PlanError:
            assert expected is None
        else:
            assert expected is not None
            totals = validate_plan(occurrences, purchases, distance_m)
            assert abs(totals["cost"] - D(expected * 5)) < D("1e-20")
