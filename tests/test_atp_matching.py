import copy

import pytest

from stations.atp_matching import coordinates, match_feature

STATION = {
    "brand_hints": ["Love's"],
    "possible_branch_references": ["382"],
    "state": "CA",
    "city": "Tulare",
}
FEATURE = {
    "id": "synthetic-branch-382",
    "geometry": {"type": "Point", "coordinates": [-119.33, 36.18]},
    "properties": {
        "@spider": "loves_us",
        "ref": "382",
        "brand": "Love's",
        "addr:country": "US",
        "addr:state": "CA",
        "addr:city": "Tulare",
        "addr:street_address": "123 Example Street",
        "highway": "services",
        "fuel:diesel": "yes",
        "@source_uri": "https://example.org/operator",
    },
}


def test_source_specific_branch_match_without_geocoder_confidence():
    assert match_feature(STATION, FEATURE, "loves_us")[0] == "accepted"


@pytest.mark.parametrize(
    "changes",
    [
        {"ref": "383"},
        {"ref": "0382"},
        {"brand": "Speedco"},
        {"brand": ""},
        {"addr:country": "CA"},
        {"addr:state": "NV"},
        {"addr:city": ""},
        {"addr:city": "Fresno"},
        {"fuel:diesel": "no"},
        {"addr:street_address": ""},
        {"@spider": "other"},
        {"end_date": "yes"},
        {"@source_uri": ""},
    ],
)
def test_missing_and_conflicting_evidence_is_not_agreement(changes):
    feature = copy.deepcopy(FEATURE)
    feature["properties"].update(changes)
    assert match_feature(STATION, feature, "loves_us")[0] != "accepted"


def test_city_punctuation_normalization_does_not_erase_branch_evidence():
    feature = copy.deepcopy(FEATURE)
    feature["properties"]["addr:city"] = "Mc Calla"
    station = {**STATION, "city": "McCalla"}
    assert match_feature(station, feature, "loves_us")[0] == "accepted"


@pytest.mark.parametrize(
    "geometry",
    [
        None,
        {"type": "Point", "coordinates": [True, 30]},
        {"type": "Point", "coordinates": [0, float("nan")]},
        {"type": "Polygon", "coordinates": []},
        {"type": "Point", "coordinates": [200, 30]},
    ],
)
def test_missing_centroid_and_invalid_geometry_cannot_be_accepted(geometry):
    feature = {**FEATURE, "geometry": geometry}
    assert coordinates(feature) is None
    assert match_feature(STATION, feature, "loves_us")[0] == "review_required"


def test_competing_employer_branch_aliases_require_review():
    assert (
        match_feature(
            {**STATION, "possible_branch_references": ["382", "383"]}, FEATURE, "loves_us"
        )[0]
        == "review_required"
    )


def test_wrong_namespace_cannot_reuse_a_numerically_equal_reference():
    assert (
        match_feature({**STATION, "brand_hints": ["QuikTrip"]}, FEATURE, "loves_us")[0]
        == "rejected"
    )
