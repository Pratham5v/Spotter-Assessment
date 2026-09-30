from stations.enrichment import match_candidate, station_name

SOURCE = {
    "Truckstop Name": "PILOT TRAVEL CENTERS #388",
    "State": "MS",
    "City": "Meridian",
    "Address": "I-20 EXIT 151",
}


def test_high_confidence_wrong_branch_is_not_accepted():
    feature = {
        "country_code": "us",
        "state_code": "MS",
        "city": "Meridian",
        "name": "Pilot",
        "category": "service.vehicle.fuel",
        "result_type": "amenity",
        "rank": {"confidence": 1},
    }
    assert match_candidate(SOURCE, feature)[0] == "review_required"
    feature["store_ref"] = "388"
    assert match_candidate(SOURCE, feature)[0] == "accepted"
    feature["state_code"] = "AL"
    assert match_candidate(SOURCE, feature)[0] == "rejected"


def test_interpolated_building_and_centroid_are_not_accepted():
    for kind in ["building", "city", "street"]:
        feature = {
            "country_code": "us",
            "state_code": "MS",
            "name": "Pilot",
            "result_type": kind,
            "category": "service.vehicle.fuel",
            "store_ref": "388",
        }
        assert match_candidate(SOURCE, feature)[0] != "accepted"


def test_preserve_branch_number_and_nonfuel_rejection():
    assert station_name("FLYING J TRAVEL PLAZA #665") == ("Flying J", "665")
    assert station_name("LOVES TRAVEL STOP #752") == ("Love's", "752")
    feature = {
        "country_code": "us",
        "state_code": "MS",
        "name": "Pilot",
        "result_type": "amenity",
        "category": "leisure.park",
        "store_ref": "388",
    }
    assert match_candidate(SOURCE, feature)[0] == "review_required"
