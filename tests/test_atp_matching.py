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


def prepared_sources(tmp_path, extra_identity=False, extra_feature=False):
    import csv
    import hashlib
    import json

    from stations.ingestion import HEADERS, audit_csv

    source = tmp_path / "employer.csv"
    with source.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerow(["one", "LOVES #382", "I-99 EXIT 1", "Tulare", "CA", "rack", "3"])
        if extra_identity:
            writer.writerow(["two", "LOVES #382", "I-99 EXIT 1", "Tulare", "CA", "rack", "2"])
    features = [copy.deepcopy(FEATURE)]
    if extra_feature:
        features.append({**copy.deepcopy(FEATURE), "id": "competing-feature"})
    raw = json.dumps({"features": features}).encode()
    (tmp_path / "loves.geojson").write_bytes(raw)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "release": "synthetic-release",
                "retrieved_at": "2026-10-01T00:00:00Z",
                "sources": [
                    {
                        "status": "available",
                        "collector": "loves_us",
                        "file": "loves.geojson",
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "reference_semantics": "synthetic store number",
                        "coordinate_origin": "synthetic operator coordinates",
                        "url": "https://example.org/published",
                        "licence": "synthetic",
                    }
                ],
            }
        )
    )
    return audit_csv(source), manifest


def test_two_employer_ids_claiming_one_pin_remain_separate_and_unaccepted(tmp_path):
    import json

    from stations.atp_matching import match_sources
    from stations.enrichment import load_artifact

    audit, manifest = prepared_sources(tmp_path, extra_identity=True)
    artifact, report = match_sources(audit, manifest, lambda point: True)
    assert len(artifact["records"]) == 2
    assert all(r["status"] == "review_required" for r in artifact["records"])
    assert report["summary"]["candidate_identities"] == 2
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact))
    assert len(load_artifact(path, audit)[1]) == 2


def test_competing_features_and_outside_US_points_are_not_accepted(tmp_path):
    from stations.atp_matching import match_sources

    audit, manifest = prepared_sources(tmp_path, extra_feature=True)
    artifact, _ = match_sources(audit, manifest, lambda point: True)
    assert artifact["records"][0]["evidence"]["identity_reason"] == ["competing_source_features"]
    audit, manifest = prepared_sources(tmp_path)
    artifact, _ = match_sources(audit, manifest, lambda point: False)
    assert artifact["records"][0]["status"] == "review_required"
    assert artifact["records"][0]["latitude"] is None


def test_changed_published_bytes_fail_before_matching(tmp_path):
    from stations.atp_matching import match_sources
    from stations.ingestion import AuditError

    audit, manifest = prepared_sources(tmp_path)
    (tmp_path / "loves.geojson").write_text('{"features": []}')
    with pytest.raises(AuditError, match="checksum"):
        match_sources(audit, manifest, lambda point: True)


def test_new_identity_conflict_is_never_overridden_by_legacy_acceptance(tmp_path):
    from stations.atp_matching import match_sources, reconcile_baseline

    audit, manifest = prepared_sources(tmp_path)
    artifact, _ = match_sources(audit, manifest, lambda point: True)
    previous = copy.deepcopy(artifact["records"][0])
    record = artifact["records"][0]
    record.update(status="review_required", latitude=None, longitude=None)
    record["evidence"]["identity_reason"] = ["brand_mismatch"]
    decisions = reconcile_baseline(artifact, {"one": previous}, audit, lambda point: True)
    assert record["status"] == "review_required"
    assert decisions[0]["outcome"] == "new_ambiguity_not_overridden"


def test_changed_physical_address_blocks_legacy_reconciliation(tmp_path):
    from stations.atp_matching import match_sources, reconcile_baseline

    audit, manifest = prepared_sources(tmp_path)
    artifact, _ = match_sources(audit, manifest, lambda point: True)
    previous = copy.deepcopy(artifact["records"][0])
    previous["evidence"]["official_location"] = {"address": "A different street"}
    decisions = reconcile_baseline(artifact, {"one": previous}, audit, lambda point: True)
    assert artifact["records"][0]["status"] == "review_required"
    assert artifact["records"][0]["latitude"] is None
    assert decisions[0]["outcome"] == "conflict_excluded"


def test_legacy_fuel_evidence_is_rechecked_and_shared_pin_is_excluded(tmp_path):
    from stations.atp_matching import match_sources, reconcile_baseline

    audit, manifest = prepared_sources(tmp_path, extra_identity=True)
    artifact, _ = match_sources(audit, manifest, lambda point: True)
    baseline = {}
    for record in artifact["records"]:
        station_id = record["opis_id"]
        audit.stations[station_id]["fields"]["Truckstop Name"] = "PILOT #382"
        previous = copy.deepcopy(record)
        previous.update(status="accepted", longitude=-119.3, latitude=36.1)
        previous["evidence"]["official_location"] = {
            "store_number": "382",
            "name": "Pilot",
            "country": "US",
            "state": "CA",
            "city": "Tulare",
            "fuel_lanes": 4,
            "latitude": 36.1,
            "longitude": -119.3,
        }
        baseline[station_id] = previous
        record.update(status="unresolved", latitude=None, longitude=None)
        record["evidence"]["identity_reason"] = ["no_supported_source_reference_candidate"]
    one = {**artifact, "records": [copy.deepcopy(artifact["records"][0])]}
    decisions = reconcile_baseline(one, baseline, audit, lambda point: True)
    assert one["records"][0]["status"] == "accepted"
    assert decisions[0]["outcome"] == "legacy_operator_evidence_rechecked_and_retained"
    reconcile_baseline(artifact, baseline, audit, lambda point: True)
    assert all(r["status"] == "review_required" for r in artifact["records"])
    assert all(r["latitude"] is None for r in artifact["records"])
