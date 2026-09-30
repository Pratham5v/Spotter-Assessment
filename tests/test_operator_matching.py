import pytest

from stations.operator_matching import match_pilot

SOURCE = {"Truckstop Name": "PILOT #388", "City": "Meridian", "State": "MS"}
LOCATION = {
    "store_number": "388",
    "name": "Pilot Travel Center",
    "city": "Meridian",
    "state": "MS",
    "country": "US",
    "fuel_lanes": "7",
    "latitude": 32.346,
    "longitude": -88.728,
}


def test_official_store_match_requires_branch_and_fuel_identity():
    assert match_pilot(SOURCE, LOCATION)[0] == "accepted"


@pytest.mark.parametrize(
    "changes",
    [
        {"store_number": "389"},
        {"name": "ONE9 Travel Center"},
        {"city": "Jackson"},
        {"state": "AL"},
        {"country": "CA"},
        {"fuel_lanes": "0"},
        {"latitude": float("nan")},
        {"longitude": True},
    ],
)
def test_operator_mismatches_cannot_be_accepted(changes):
    assert match_pilot(SOURCE, {**LOCATION, **changes})[0] != "accepted"


def test_unrelated_chain_cannot_use_overlapping_store_reference():
    assert match_pilot({**SOURCE, "Truckstop Name": "LOVE'S #388"}, LOCATION)[0] == "unresolved"
