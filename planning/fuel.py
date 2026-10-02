"""Optimal divisible purchases on a fixed ordered itinerary, independent of Django."""

from decimal import Decimal, localcontext

from planning.domain import FuelPurchase, PlanError

METRES_PER_MILE = Decimal("1609.344")
MPG = Decimal(10)
CAPACITY = Decimal(50)
RANGE_M = CAPACITY * MPG * METRES_PER_MILE
ARITHMETIC_TOLERANCE_M = Decimal("1e-8")
VERSION = "greedy_decimal_v1"


def solve(occurrences, distance_m):
    with localcontext() as context:
        context.prec = 40
        return _solve(occurrences, Decimal(str(distance_m)))


def _solve(occurrences, distance):
    if not distance.is_finite() or distance < 0:
        raise ValueError("Invalid distance")
    at_position = {}
    for node in occurrences:
        if (
            not node.position_m.is_finite()
            or not node.price.is_finite()
            or node.price <= 0
            or not 0 <= node.position_m <= distance
        ):
            raise ValueError("Invalid station occurrence")
        if node.position_m == distance:
            continue
        previous = at_position.get(node.position_m)
        if previous is None or (node.price, node.station_id, node.occurrence_id) < (
            previous.price,
            previous.station_id,
            previous.occurrence_id,
        ):
            at_position[node.position_m] = node
    nodes = sorted(at_position.values(), key=lambda n: n.position_m)
    positions = [n.position_m for n in nodes] + [distance]
    prices = [n.price for n in nodes] + [Decimal(0)]
    lower, stack = [None] * len(positions), []
    for index in range(len(positions) - 1, -1, -1):
        while stack and prices[stack[-1]] >= prices[index]:
            stack.pop()
        lower[index] = stack[-1] if stack else None
        stack.append(index)
    fuel_m, previous_m, purchases = RANGE_M, Decimal(0), []
    for index, position in enumerate(positions):
        fuel_m -= position - previous_m
        if fuel_m < -ARITHMETIC_TOLERANCE_M:
            raise PlanError(
                "INSUFFICIENT_STATION_COVERAGE",
                "The fixed itinerary exceeds available fuel range.",
                details={"unreachable_position_m": str(position)},
            )
        fuel_m = max(Decimal(0), fuel_m)
        previous_m = position
        if index == len(nodes):
            break
        # Greedy purchase rule: buy only enough to reach the first cheaper station within full-tank range; otherwise fill up, capped by fuel needed to finish.
        # Quantities are optimal for this fixed itinerary; route/stop selection is heuristic.
        # Fuel quantities here represent the distance they can cover, in metres.
        cheaper = lower[index]
        target = (
            positions[cheaper] - position
            if cheaper is not None and positions[cheaper] - position <= RANGE_M
            else min(RANGE_M, distance - position)
        )
        bought_m = max(Decimal(0), target - fuel_m)
        if bought_m:
            node = nodes[index]
            gallons = bought_m / METRES_PER_MILE / MPG
            arrival = fuel_m / METRES_PER_MILE / MPG
            purchases.append(
                FuelPurchase(
                    node.occurrence_id,
                    node.station_id,
                    position,
                    node.price,
                    gallons,
                    gallons * node.price,
                    arrival,
                    arrival + gallons,
                )
            )
            fuel_m += bought_m
    return purchases
