import time
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from planning import geometry
from planning.cache import get_json, key, set_json
from planning.domain import PlanError
from planning.fuel import RANGE_M, VERSION, solve
from planning.geography import validate_endpoint
from planning.providers.ors import VERSION as ROUTING_VERSION
from planning.providers.ors import RoutingBudget, directions
from planning.validation import cents, decimal_string, validate_plan
from stations.models import DatasetImport


def point_object(point):
    return {"longitude": point[0], "latitude": point[1]}


def routed_purchases(route, selected):
    position = Decimal(0)
    occurrences = []
    for leg, candidate in zip(route["legs_m"], selected, strict=False):
        position += Decimal(leg)
        occurrences.append(replace(candidate["occurrence"], position_m=position))
    distance = Decimal(route["distance_m"])
    purchases = solve(occurrences, distance)
    totals = validate_plan(occurrences, purchases, distance)
    return occurrences, purchases, totals


def bridge_candidates(all_candidates, selected, route):
    existing = {c["occurrence"].occurrence_id for c in selected}
    positions = [Decimal(0), *(c["occurrence"].position_m for c in selected)]
    end = max((c["occurrence"].position_m for c in all_candidates), default=Decimal(0))
    # Last bound uses the projected base-route destination supplied by the caller.
    positions.append(max(end, Decimal(route.get("base_distance_m", route["distance_m"]))))
    additions = []
    for index, leg in enumerate(route["legs_m"]):
        if Decimal(leg) <= RANGE_M:
            continue
        left, right = positions[index : index + 2]
        eligible = [
            c
            for c in all_candidates
            if c["occurrence"].occurrence_id not in existing
            and left < c["occurrence"].position_m < right
        ]
        if not eligible:
            raise PlanError(
                "NO_VERIFIED_PLAN",
                "No accepted bridge candidate is available for a verified fuel gap.",
            )
        midpoint = (left + right) / 2
        additions.append(
            min(
                eligible,
                key=lambda c: (
                    abs(c["occurrence"].position_m - midpoint),
                    c["offset_m"],
                    c["occurrence"].price,
                    c["occurrence"].station_id,
                ),
            )
        )
    if not additions:
        raise PlanError("NO_VERIFIED_PLAN", "The selected itinerary could not be repaired.")
    return sorted([*selected, *additions], key=lambda c: c["occurrence"].position_m)


def build_plan(start, finish):
    started = time.perf_counter()
    boundary_version = validate_endpoint(start)
    validate_endpoint(finish)
    dataset = DatasetImport.objects.filter(is_active=True, status="complete").first()
    if not dataset:
        raise PlanError("DATA_NOT_READY", "No completed station dataset is active.", 503)
    cache_key = key(
        "plan",
        [
            start,
            finish,
            dataset.fingerprint,
            boundary_version,
            VERSION,
            geometry.VERSION,
            ROUTING_VERSION,
            "full50_partial_zeroreserve",
            100,
            350,
        ],
    )
    cached = get_json(cache_key)
    if cached and get_json("map:" + cached["plan_id"]) is not None:
        cached["diagnostics"].update(
            routing_attempts_this_request=0,
            route_cache_hits=0,
            plan_cache_hit=True,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return cached
    all_candidates, selected, repair = [], [], False
    with RoutingBudget() as budget:
        if start == finish:
            base = {
                "geometry": {"type": "Point", "coordinates": start},
                "distance_m": "0",
                "duration_seconds": 0,
                "legs_m": ["0"],
                "snapped": [start, finish],
                "snap_distances_m": [0, 0],
                "warnings": [],
            }
            final = base
        else:
            base = directions([start, finish], [350, 350], budget)
            final = base
            if Decimal(base["distance_m"]) > RANGE_M:
                all_candidates = geometry.candidates(base, dataset.id)
                projected = solve(
                    [c["occurrence"] for c in all_candidates], Decimal(base["distance_m"])
                )
                by_id = {c["occurrence"].occurrence_id: c for c in all_candidates}
                selected = [by_id[p.occurrence_id] for p in projected]
                coordinates = [
                    start,
                    *[[c["station"]["longitude"], c["station"]["latitude"]] for c in selected],
                    finish,
                ]
                final = directions(coordinates, [350, *[100] * len(selected), 350], budget)
        try:
            occurrences, purchases, totals = routed_purchases(final, selected)
        except PlanError as exc:
            if budget.attempts >= 3 or not selected:
                raise PlanError(
                    "NO_VERIFIED_PLAN", "Actual routed legs cannot support the selected fuel plan."
                ) from exc
            final["base_distance_m"] = base["distance_m"]
            selected = bridge_candidates(all_candidates, selected, final)
            repair = True
            final = directions(
                [
                    start,
                    *[[c["station"]["longitude"], c["station"]["latitude"]] for c in selected],
                    finish,
                ],
                [350, *[100] * len(selected), 350],
                budget,
            )
            try:
                occurrences, purchases, totals = routed_purchases(final, selected)
            except PlanError as repair_error:
                raise PlanError(
                    "NO_VERIFIED_PLAN",
                    "One bounded itinerary repair did not produce a feasible fuel plan.",
                ) from repair_error
    by_purchase = {p.occurrence_id: p for p in purchases}
    visited, stops = [], []
    for sequence, (candidate, occurrence) in enumerate(zip(selected, occurrences, strict=True), 1):
        station = candidate["station"]
        purchase = by_purchase.get(occurrence.occurrence_id)
        visited.append(
            {
                "sequence": sequence,
                "station_id": station["opis_id"],
                "occurrence_id": occurrence.occurrence_id,
                "name": station["name"],
                "source_address": f"{station['address']}, {station['city']}, {station['state']}",
                "facility_location": {
                    "latitude": station["latitude"],
                    "longitude": station["longitude"],
                },
                "routed_location": point_object(final["snapped"][sequence]),
                "snap_distance_m": final["snap_distances_m"][sequence],
                "leg_distance_m": final["legs_m"][sequence - 1],
                "cumulative_distance_m": str(occurrence.position_m),
                "purchased_here": bool(purchase),
            }
        )
        if purchase:
            stops.append(
                {
                    "visited_station_sequence": sequence,
                    "station_id": station["opis_id"],
                    "price_usd_per_gallon": str(purchase.price),
                    "price_policy": dataset.price_policy,
                    "distinct_price_count": station["distinct_price_count"],
                    "price_range": [str(station["min_price"]), str(station["max_price"])],
                    "gallons_purchased": decimal_string(purchase.gallons),
                    "cost_usd": str(cents(purchase.cost)),
                    "arrival_gallons": decimal_string(purchase.arrival_gallons),
                    "departure_gallons": decimal_string(purchase.departure_gallons),
                }
            )
    # Independent revalidation of the quantities actually exposed to callers.
    serialized = [
        replace(
            p,
            gallons=Decimal(decimal_string(p.gallons)),
            cost=Decimal(decimal_string(p.gallons)) * p.price,
            arrival_gallons=Decimal(decimal_string(p.arrival_gallons)),
            departure_gallons=Decimal(decimal_string(p.departure_gallons)),
        )
        for p in purchases
    ]
    validate_plan(
        occurrences,
        serialized,
        Decimal(final["distance_m"]),
        tolerance=Decimal("1e-12") * (len(serialized) + 2),
    )
    now, plan_id = timezone.now(), str(uuid.uuid4())
    response = {
        "plan_id": plan_id,
        "generated_at": now.isoformat(),
        "map_url": reverse("plan-map", args=[plan_id]),
        "map_expires_at": (now + timedelta(hours=1)).isoformat(),
        "input": {"start": point_object(start), "finish": point_object(finish)},
        "route": {
            "geometry": final["geometry"],
            "base_distance_m": base["distance_m"],
            "distance_m": final["distance_m"],
            "distance_miles": decimal_string(Decimal(final["distance_m"]) / Decimal("1609.344")),
            "duration_seconds": final["duration_seconds"],
            "additional_itinerary_distance_m": str(
                Decimal(final["distance_m"]) - Decimal(base["distance_m"])
            ),
            "requested_endpoints": [point_object(start), point_object(finish)],
            "snapped_endpoints": [
                point_object(final["snapped"][0]),
                point_object(final["snapped"][-1]),
            ],
            "endpoint_snap_distances_m": [
                final["snap_distances_m"][0],
                final["snap_distances_m"][-1],
            ],
            "leg_distances_m": final["legs_m"],
        },
        "visited_stations": visited,
        "fuel_stops": stops,
        "fuel": {
            "initial_gallons": "50",
            "capacity_gallons": "50",
            "mpg": "10",
            "consumed_gallons": decimal_string(totals["consumed"]),
            "purchased_gallons": decimal_string(totals["purchased"]),
            "remaining_gallons": decimal_string(totals["remaining"]),
            "total_cost_usd": str(sum((Decimal(s["cost_usd"]) for s in stops), Decimal("0.00"))),
        },
        "assumptions": {
            "full_start": True,
            "partial_fills": True,
            "zero_destination_reserve": True,
            "currency": "USD",
            "volume_unit": "US gallon",
            "initial_fuel_cost_excluded": True,
            "access_mileage_included": True,
            "route_verified_to_provider_waypoints": True,
            "optimization_scope": "fixed_selected_itinerary_purchase_optimum",
            "stop_selection": "projected_candidate_heuristic",
        },
        "provenance": {
            "dataset_version": str(dataset.id),
            "dataset_imported_at": dataset.imported_at.isoformat(),
            "price_observed_at": None,
            "enrichment_version": dataset.enrichment_version,
            "price_policy_version": dataset.price_policy,
            "algorithm_version": VERSION,
            "boundary_version": boundary_version,
            "provider": "openrouteservice",
            "profile": "driving-hgv",
        },
        "diagnostics": {
            "routing_attempts_this_request": budget.attempts,
            "route_cache_hits": budget.cache_hits,
            "plan_cache_hit": False,
            "accepted_candidate_count": len(all_candidates),
            "selected_waypoint_count": len(selected),
            "repair_used": repair,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        },
        "warnings": [
            "Prices are a supplied snapshot with unknown grade and observation date.",
            (
                "Only station coordinates accepted under the documented matching rules "
                "participate; coverage may be incomplete."
            ),
        ],
    }
    set_json("map:" + plan_id, response)
    set_json(cache_key, response)
    return response
