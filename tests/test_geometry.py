from unittest.mock import patch

import pytest
from shapely.geometry import Polygon, box
from shapely.prepared import prep

from planning.domain import PlanError
from planning.geography import validate_endpoint, validate_geometry
from planning.geometry import GEOD, candidates


def road(points):
    distance = GEOD.line_length(*zip(*points, strict=True))
    return {"geometry": {"type": "LineString", "coordinates": points}, "distance_m": str(distance)}


def test_segment_projection_finds_station_between_sparse_vertices(active_dataset):
    active_dataset.stations.update(longitude=-99, latitude=35)
    result = candidates(road([[-100, 35], [-98, 35]]), active_dataset.id)
    assert len(result) == 1
    assert result[0]["offset_m"] < 600
    assert 85000 < float(result[0]["occurrence"].position_m) < 100000


def test_reverse_direction_and_loop_occurrences_are_retained(active_dataset):
    active_dataset.stations.update(longitude=-99, latitude=35)
    points = [[-100, 35], [-98, 35], [-97, 35], [-97, 36], [-100, 36], [-100, 35], [-98, 35]]
    forward = candidates(road(points), active_dataset.id)
    reverse = candidates(road(points[::-1]), active_dataset.id)
    assert len(forward) == len(reverse) == 2
    assert forward[0]["occurrence"].position_m < forward[1]["occurrence"].position_m
    assert {r["occurrence"].occurrence_id for r in forward} == {"001:0", "001:1"}


def test_unaccepted_and_outside_corridor_stations_are_excluded(active_dataset):
    active_dataset.stations.update(longitude=-99, latitude=35.1)
    assert candidates(road([[-100, 35], [-98, 35]]), active_dataset.id) == []
    active_dataset.stations.update(longitude=-99, latitude=35, coordinate_status="review_required")
    assert candidates(road([[-100, 35], [-98, 35]]), active_dataset.id) == []


def test_whole_route_check_detects_foreign_hole_between_valid_endpoints():
    polygon = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)], holes=[[(1, 1), (3, 1), (3, 3), (1, 3)]])
    with patch(
        "planning.geography.boundary", return_value=(prep(polygon), box(10, 10, 11, 11), "test")
    ):
        assert validate_endpoint([0, 2]) == validate_endpoint([4, 2]) == "test"
        with pytest.raises(PlanError) as route:
            validate_geometry([[0, 2], [4, 2]])
        assert route.value.code == "ROUTE_GEOGRAPHY_UNVERIFIED"
        with pytest.raises(PlanError) as territory:
            validate_endpoint([10.5, 10.5])
        assert territory.value.code == "UNSUPPORTED_US_JURISDICTION"
        with pytest.raises(PlanError) as foreign:
            validate_endpoint([20, 20])
        assert foreign.value.code == "OUTSIDE_US"


def test_station_without_segment_hits_does_not_construct_transformer(active_dataset):
    # Inside the route's database bounding box, far from every segment.
    active_dataset.stations.update(longitude=-99, latitude=35.3)
    with patch("planning.geometry.Transformer.from_crs") as transformer:
        assert candidates(road([[-100, 35], [-100, 36], [-98, 36]]), active_dataset.id) == []
    transformer.assert_not_called()
