"""Strict Pilot export joins; never infer identities for unrelated operators."""

import math

from stations.enrichment import station_name, words

VERSION = "pilot_official_reference_city_v1"


def match_pilot(fields, location):
    brand, number = station_name(fields["Truckstop Name"])
    reasons = []
    if brand not in ("Pilot", "Flying J") or not number:
        return "unresolved", ["outside_operator_policy"]
    if str(location.get("store_number")) != number:
        return "rejected", ["store_reference_mismatch"]
    if words(brand) not in words(location.get("name", "")):
        reasons.append("brand_mismatch")
    if location.get("country") != "US" or location.get("state") != fields["State"]:
        reasons.append("country_or_state_mismatch")
    if words(location.get("city", "")) != words(fields["City"]):
        reasons.append("city_mismatch")
    lanes = location.get("fuel_lanes")
    try:
        if float(lanes) <= 0 or not math.isfinite(float(lanes)):
            reasons.append("fuel_lanes_unconfirmed")
    except (TypeError, ValueError):
        reasons.append("fuel_lanes_unconfirmed")
    lat, lon = location.get("latitude"), location.get("longitude")
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in (lat, lon)
    ):
        reasons.append("invalid_coordinates")
    elif not -90 <= lat <= 90 or not -180 <= lon <= 180:
        reasons.append("invalid_coordinates")
    return (
        ("review_required", reasons)
        if reasons
        else ("accepted", ["official_operator_store_number_brand_state_city_fuel_lanes"])
    )
