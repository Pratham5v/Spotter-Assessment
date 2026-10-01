import math
from decimal import Decimal

import numpy as np
from pyproj import Geod, Transformer
from shapely import STRtree
from shapely.geometry import LineString, box

from planning.domain import PlanError, StationOccurrence
from stations.models import Station

GEOD = Geod(ellps="WGS84")
CORRIDOR_M = 1609.344
VERSION = "segment_occurrences_1mile_v1"


def candidates(route, dataset_id):
    points = np.array(route["geometry"]["coordinates"], dtype=float)
    if np.ptp(points[:, 0]) > 180:
        raise PlanError(
            "ROUTE_GEOGRAPHY_UNVERIFIED", "Dateline-crossing candidate geometry is unsupported."
        )
    north = max(abs(points[:, 1].min()), abs(points[:, 1].max()))
    lat_margin, lon_margin = (
        CORRIDOR_M / 110000,
        CORRIDOR_M / (110000 * max(0.05, math.cos(math.radians(north)))),
    )
    stations = list(
        Station.objects.filter(
            dataset_id=dataset_id,
            coordinate_status="accepted",
            latitude__gte=points[:, 1].min() - lat_margin,
            latitude__lte=points[:, 1].max() + lat_margin,
            longitude__gte=points[:, 0].min() - lon_margin,
            longitude__lte=points[:, 0].max() + lon_margin,
        ).values(
            "opis_id",
            "name",
            "address",
            "city",
            "state",
            "latitude",
            "longitude",
            "price",
            "min_price",
            "max_price",
            "distinct_price_count",
            "location_evidence",
        )
    )
    segments = [LineString([a, b]) for a, b in zip(points, points[1:], strict=False)]
    tree = STRtree(segments)
    _, _, lengths = GEOD.inv(points[:-1, 0], points[:-1, 1], points[1:, 0], points[1:, 1])
    cumulative = np.r_[0.0, np.cumsum(lengths)]
    if cumulative[-1] <= 0:
        raise PlanError(
            "INVALID_PROVIDER_RESPONSE", "Positive route has zero geometry length.", 502
        )
    scale = float(route["distance_m"]) / cumulative[-1]
    if not 0.95 <= scale <= 1.05:
        raise PlanError(
            "INVALID_PROVIDER_RESPONSE",
            "Geometry distance differs materially from reported route distance.",
            502,
        )
    result = []
    for station in stations:
        lon, lat = station["longitude"], station["latitude"]
        indices = sorted(
            int(i)
            for i in tree.query(
                box(lon - lon_margin, lat - lat_margin, lon + lon_margin, lat + lat_margin)
            )
        )
        if not indices:
            continue
        project = Transformer.from_crs(
            4326, f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m", always_xy=True
        )
        hits = []
        for i in indices:
            x, y = project.transform(points[i : i + 2, 0], points[i : i + 2, 1])
            a, delta = np.array([x[0], y[0]]), np.array([x[1] - x[0], y[1] - y[0]])
            norm = float(delta @ delta)
            fraction = float(np.clip(-(a @ delta) / norm, 0, 1)) if norm > 0 else 0
            offset = float(np.linalg.norm(a + fraction * delta))
            if offset <= CORRIDOR_M:
                hits.append((i, offset, (cumulative[i] + fraction * lengths[i]) * scale))
        groups = []
        for hit in hits:
            if not groups or hit[0] > groups[-1][-1][0] + 1:
                groups.append([])
            groups[-1].append(hit)
        for passage, group in enumerate(groups):
            _, offset, marker = min(group, key=lambda h: (h[1], h[0]))
            occurrence = StationOccurrence(
                f"{station['opis_id']}:{passage}",
                station["opis_id"],
                Decimal(str(marker)),
                station["price"],
            )
            result.append({"occurrence": occurrence, "station": station, "offset_m": offset})
    return sorted(result, key=lambda r: (r["occurrence"].position_m, r["occurrence"].occurrence_id))
