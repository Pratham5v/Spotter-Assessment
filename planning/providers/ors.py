import math
import time
from dataclasses import dataclass, field
from decimal import Decimal

import httpx
from django.conf import settings
from pyproj import Geod

from planning.cache import get_json, key, set_json
from planning.domain import PlanError
from planning.geography import validate_geometry

GEOD = Geod(ellps="WGS84")
VERSION = "ors_hgv_vehicle_type_v2"
URL = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"


@dataclass
class RoutingBudget:
    attempts: int = 0
    cache_hits: int = 0
    started: float = field(default_factory=time.monotonic)

    def remaining_seconds(self):
        return 35 - (time.monotonic() - self.started)

    def consume(self):
        if self.attempts >= 3 or self.remaining_seconds() <= 0:
            raise PlanError("NO_VERIFIED_PLAN", "Routing budget or deadline exhausted.")
        self.attempts += 1


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)


def normalize_response(body, requested, radiuses):
    try:
        features = body["features"]
        if len(features) != 1:
            raise ValueError("Expected one route")
        feature = features[0]
        geometry, properties = feature["geometry"], feature["properties"]
        points = geometry["coordinates"]
        if (
            geometry["type"] != "LineString"
            or len(points) < 2
            or any(
                len(p) < 2
                or not all(finite(v) for v in p[:2])
                or not -180 <= p[0] <= 180
                or not -90 <= p[1] <= 90
                for p in points
            )
        ):
            raise ValueError("Invalid geometry")
        points = [p[:2] for p in points]
        distance, duration = properties["summary"]["distance"], properties["summary"]["duration"]
        segments, indices = properties["segments"], properties["way_points"]
        if (
            not finite(distance)
            or not finite(duration)
            or distance < 0
            or duration < 0
            or len(segments) != len(requested) - 1
            or len(indices) != len(requested)
        ):
            raise ValueError("Invalid distance/leg count")
        if (
            any(
                isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(points)
                for i in indices
            )
            or indices != sorted(indices)
            or indices[0] != 0
            or indices[-1] != len(points) - 1
        ):
            raise ValueError("Invalid waypoint indices")
        legs = [s["distance"] for s in segments]
        if any(not finite(v) or v < 0 for v in legs) or abs(
            sum(Decimal(str(v)) for v in legs) - Decimal(str(distance))
        ) > Decimal("0.1") * len(legs):
            raise ValueError("Inconsistent legs")
        snapped = [points[i] for i in indices]
        displacements = [
            abs(GEOD.inv(*raw, *snap)[2]) for raw, snap in zip(requested, snapped, strict=True)
        ]
        for i, (displacement, radius) in enumerate(zip(displacements, radiuses, strict=True)):
            if displacement > radius:
                raise PlanError(
                    "STATION_ACCESS_UNVERIFIED"
                    if 0 < i < len(requested) - 1
                    else "ROUTE_GEOGRAPHY_UNVERIFIED",
                    "Returned waypoint exceeds the permitted snap displacement.",
                    details={"waypoint": i},
                )
        countries = properties.get("extras", {}).get("countryinfo", {}).get("values", [])
        previous = 0
        for interval in countries:
            if (
                len(interval) != 3
                or interval[0] != previous
                or not interval[0] <= interval[1] < len(points)
            ):
                raise ValueError("Invalid country intervals")
            previous = interval[1]
            if interval[2] not in (0, 214):
                raise PlanError(
                    "ROUTE_GEOGRAPHY_UNVERIFIED",
                    "Provider reports a foreign-country route interval.",
                )
        if countries and previous != len(points) - 1:
            raise ValueError("Incomplete country intervals")
        validate_geometry(points)
        return {
            "geometry": {"type": "LineString", "coordinates": points},
            "distance_m": str(distance),
            "duration_seconds": duration,
            "legs_m": [str(v) for v in legs],
            "snapped": snapped,
            "snap_distances_m": displacements,
            "warnings": properties.get("warnings", []),
        }
    except PlanError:
        raise
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise PlanError(
            "INVALID_PROVIDER_RESPONSE",
            "Routing provider returned an invalid or inconsistent route.",
            502,
        ) from exc


def directions(coordinates, radiuses, budget):
    if not 2 <= len(coordinates) <= 50:
        raise PlanError("ROUTE_LIMIT_EXCEEDED", "A route supports 2–50 waypoints.")
    direct = sum(
        abs(GEOD.inv(*a, *b)[2]) for a, b in zip(coordinates, coordinates[1:], strict=False)
    )
    if direct > 6_000_000:
        raise PlanError(
            "ROUTE_LIMIT_EXCEEDED", "The itinerary exceeds the hosted routing distance limit."
        )
    payload = {
        "coordinates": coordinates,
        "radiuses": radiuses,
        "instructions": True,
        "extra_info": ["countryinfo"],
        "options": {"avoid_borders": "all", "vehicle_type": "hgv"},
    }
    cache_key = key("route", [VERSION, payload])
    cached = get_json(cache_key)
    if cached:
        validate_geometry(cached["geometry"]["coordinates"])
        budget.cache_hits += 1
        return cached
    if not settings.ORS_API_KEY:
        raise PlanError(
            "PROVIDER_UNAVAILABLE", "Routing provider credentials are not configured.", 503
        )
    for retry in range(2):
        budget.consume()
        remaining = max(0.1, budget.remaining_seconds())
        try:
            timeout = httpx.Timeout(min(15, remaining), connect=min(5, remaining))
            with (
                httpx.Client(timeout=timeout) as client,
                client.stream(
                    "POST", URL, json=payload, headers={"Authorization": settings.ORS_API_KEY}
                ) as response,
            ):
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    if budget.remaining_seconds() <= 0:
                        raise PlanError(
                            "PROVIDER_TIMEOUT", "Routing request deadline exceeded.", 504
                        )
                    size += len(chunk)
                    if size > 12_000_000:
                        raise PlanError(
                            "INVALID_PROVIDER_RESPONSE",
                            "Provider response exceeded the size limit.",
                            502,
                        )
                    chunks.append(chunk)
                import json

                if response.status_code >= 500 and retry == 0 and budget.attempts < 3:
                    continue
                if response.status_code in (401, 403):
                    raise PlanError(
                        "PROVIDER_UNAVAILABLE", "Routing provider configuration was rejected.", 503
                    )
                if response.status_code == 429:
                    raise PlanError(
                        "PROVIDER_QUOTA_EXCEEDED",
                        "Routing provider allowance is currently unavailable.",
                        503,
                    )
                if response.status_code in (400, 404):
                    raise PlanError(
                        "ROUTE_NOT_FOUND", "Provider could not route the requested waypoints."
                    )
                if response.status_code != 200:
                    raise PlanError("PROVIDER_UNAVAILABLE", "Routing provider is unavailable.", 503)
                normalized = normalize_response(json.loads(b"".join(chunks)), coordinates, radiuses)
                if budget.remaining_seconds() <= 0:
                    raise PlanError("PROVIDER_TIMEOUT", "Routing request deadline exceeded.", 504)
                if Decimal(normalized["distance_m"]) > 6_000_000:
                    raise PlanError(
                        "ROUTE_LIMIT_EXCEEDED", "Returned route exceeds the hosted distance limit."
                    )
                set_json(cache_key, normalized)
                return normalized
        except httpx.TimeoutException as exc:
            if retry == 0 and budget.attempts < 3:
                continue
            raise PlanError(
                "PROVIDER_TIMEOUT", "Routing provider timed out within the request budget.", 504
            ) from exc
        except httpx.HTTPError as exc:
            raise PlanError(
                "PROVIDER_UNAVAILABLE", "Routing provider connection failed.", 503
            ) from exc
        except (ValueError, TypeError) as exc:
            raise PlanError(
                "INVALID_PROVIDER_RESPONSE", "Routing provider did not return valid JSON.", 502
            ) from exc
