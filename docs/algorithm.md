# Fuel purchases on the selected itinerary

The vehicle starts with 50 US gallons, travels 10 miles per gallon, and can travel
500 miles on a full tank. Purchases are divisible. The initial tank's unknown
purchase price is excluded. The destination requires no reserve.

The optimization theorem is conditional on an ordered, fixed itinerary and its
actual routed leg distances. Choosing facilities from a one-mile corridor around
the base route is a heuristic. This implementation does not prove the globally
cheapest driving route or station set.

## Greedy rule and exchange argument

At station i, find the first strictly cheaper later station within 500 miles.
Buy only enough to reach it, after accounting for fuel already in the tank. If
none is reachable, fill up, capped by fuel needed to reach the destination. Treat
the destination as a zero-price terminal node.

Suppose a feasible plan buys extra fuel at i that it carries to a reachable
cheaper station j. Moving that amount of purchase from i to j reduces cost and
does not hurt any earlier leg: the amount being moved was still present at j.
The target quantity therefore suffices when cheaper fuel is reachable.

If no cheaper station is reachable, any fuel bought at a later station before
the next cheaper opportunity costs at least as much. Moving that purchase back
to i, up to tank capacity, preserves feasibility and never increases cost. The
greedy choice can therefore replace the corresponding part of an optimal plan.
Applying these exchanges successively gives an optimum on the fixed itinerary.
Equal prices can yield multiple optima; the implementation chooses deterministically.

## Partial-fill example

A 900-mile itinerary visits a $4 station at mile 400 and ends at mile 900.
The vehicle arrives with 10 gallons. The final 500-mile leg needs 50 gallons,
so it purchases 40 gallons for $160. Consumption is 90 gallons, purchase is
40 gallons, and the remaining tank is zero. Charging for 90 gallons would include
the starting tank and would answer a different question.

With stations at mile 300 ($4) and mile 600 ($3), on an 800-mile itinerary,
arrival at mile 300 leaves 20 gallons. Buy 10 gallons to reach cheaper fuel.
At mile 600 buy the final 20 gallons. Purchase cost is $100, not two full fills.

## Numerical and routing safeguards

Distances remain metres; the exact conversion is 1 mile = 1609.344 metres.
Decimal arithmetic uses 40 significant digits. An arithmetic tolerance of
1e-8 metres is far smaller than provider precision and never serves as a road
range reserve. Do not round miles before checking a leg. A 500.000001-mile leg
is infeasible. Quantities are serialized to 12 decimal places, then independently
re-simulated with a tolerance bounded by the serialization error.

The planner first solves projected candidates, routes positive-purchase
waypoints, then solves again using actual road legs. The final answer includes
access mileage, snapped waypoint positions and every visited facility. A facility
that needs no purchase after the second solve stays in the route and map.
One candidate-based gap repair may use the remaining routing budget. Every real
retry and repair shares the same maximum of three outbound attempts.

The independent validator checks each arrival, purchase, departure, capacity,
fuel conservation, final tank and minimal total volume. Explicit checks remain
enabled under Python's optimization mode. Line-item dollars round half-up to
cents; the total sums displayed line items.

## Complexity and regression evidence

Sort occurrences in O(n log n), then compute first-cheaper successors with a
monotonic stack in O(n). The fuel sweep uses O(n) time and O(n) storage. Exact
coincident positions retain the cheapest identity deterministically; nearby
positions are never bucketed or rounded together.

Geometry uses an STRtree of route segments, a database bounding-box filter and
station-centred metric projection. Separated passages on a loop retain distinct
occurrence identities. Runtime depends on geometry vertices and candidate hits;
the fuel solver's complexity does not describe the entire request.

The offline tests compare 2,000 seeded discrete cases with exhaustive feasible
purchase choices. Other regressions cover 499.96/500.04 miles, exact capacity,
partial fills, coincident prices, sparse vertices, reverse direction, loops,
actual-road gap repair and an unsuccessful third attempt. An independent oracle
supports the implementation; it does not establish national coordinate coverage.
