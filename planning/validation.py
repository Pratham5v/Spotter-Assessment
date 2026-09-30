"""Independent tank simulation and presentation accounting."""

from decimal import ROUND_HALF_UP, Decimal, localcontext

from planning.domain import PlanError
from planning.fuel import CAPACITY, METRES_PER_MILE, MPG


def require(condition):
    if not condition:
        raise PlanError("INVALID_FUEL_PLAN", "Independent fuel validation failed.", 500)


def validate_plan(occurrences, purchases, distance_m, tolerance=Decimal("1e-12")):
    with localcontext() as context:
        context.prec = 40
        fuel, previous, bought, cost = CAPACITY, Decimal(0), Decimal(0), Decimal(0)
        nodes = {n.occurrence_id: n for n in occurrences}
        seen = set()
        for purchase in purchases:
            node = nodes[purchase.occurrence_id]
            require(purchase.occurrence_id not in seen)
            seen.add(purchase.occurrence_id)
            require(node.station_id == purchase.station_id and node.price == purchase.price)
            require(
                node.position_m == purchase.position_m and previous <= node.position_m < distance_m
            )
            fuel -= (node.position_m - previous) / METRES_PER_MILE / MPG
            require(fuel >= -tolerance and abs(fuel - purchase.arrival_gallons) <= tolerance)
            require(
                purchase.gallons > 0
                and abs(purchase.cost - purchase.gallons * node.price) <= tolerance
            )
            fuel += purchase.gallons
            require(
                fuel <= CAPACITY + tolerance and abs(fuel - purchase.departure_gallons) <= tolerance
            )
            bought += purchase.gallons
            cost += purchase.cost
            previous = node.position_m
        consumed = distance_m / METRES_PER_MILE / MPG
        fuel -= (distance_m - previous) / METRES_PER_MILE / MPG
        require(fuel >= -tolerance)
        require(abs(CAPACITY + bought - consumed - fuel) <= tolerance)
        require(abs(bought - max(Decimal(0), consumed - CAPACITY)) <= tolerance)
        return {
            "consumed": consumed,
            "purchased": bought,
            "remaining": max(Decimal(0), fuel),
            "cost": cost,
        }


def decimal_string(value):
    return format(value.quantize(Decimal("0.000000000001")), "f")


def cents(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
