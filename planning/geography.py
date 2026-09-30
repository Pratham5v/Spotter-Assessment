import hashlib
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from shapely import from_wkb
from shapely.geometry import LineString, Point
from shapely.prepared import prep

from planning.domain import PlanError


@lru_cache(maxsize=4)
def load_boundary(path, modified):
    data = Path(path).read_bytes()
    territories = Path(path).with_name("territories.wkb")
    return (
        prep(from_wkb(data)),
        from_wkb(territories.read_bytes()) if territories.exists() else None,
        hashlib.sha256(data).hexdigest(),
    )


def boundary():
    path = settings.US_BOUNDARY_PATH
    try:
        return load_boundary(str(path), path.stat().st_mtime_ns)
    except OSError as exc:
        raise PlanError("DATA_NOT_READY", "USA boundary data has not been prepared.", 503) from exc


def validate_endpoint(coordinate):
    supported, territories, version = boundary()
    point = Point(coordinate)
    if not supported.covers(point):
        if territories is not None and territories.covers(point):
            raise PlanError(
                "UNSUPPORTED_US_JURISDICTION", "This US jurisdiction is outside supported coverage."
            )
        raise PlanError("OUTSIDE_US", "Start and finish must be inside the 50 states or DC.")
    return version


def validate_geometry(coordinates):
    supported, _, version = boundary()
    geometry = LineString(coordinates) if len(coordinates) > 1 else Point(coordinates[0])
    if not supported.covers(geometry):
        raise PlanError(
            "ROUTE_GEOGRAPHY_UNVERIFIED",
            "The complete returned route could not be verified inside the USA.",
        )
    return version
