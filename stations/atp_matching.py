"""Small offline joins for explicitly inspected ATP operator reference namespaces."""

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from stations.ingestion import AuditError
from stations.inventory import inventory

VERSION = "atp_branch_locality_v1"
# Other acquired collectors remain discovery-only until their identifiers are proven.
OPERATORS = {
    "Love's": "loves_us",
    "Kwik Trip": "kwik_trip",
    "Kwik Star": "kwik_trip",
    "Sheetz": "sheetz",
    "Pilot": "pilot_flying_j",
    "Flying J": "pilot_flying_j",
}


def text_key(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def coordinates(feature):
    geometry = feature.get("geometry") or {}
    point = geometry.get("coordinates")
    if geometry.get("type") != "Point" or not isinstance(point, list) or len(point) != 2:
        return None
    lon, lat = point
    if any(
        isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
        for v in point
    ):
        return None
    return point if -180 <= lon <= 180 and -90 <= lat <= 90 else None


def match_feature(station, feature, collector):
    p = feature.get("properties", {})
    reasons = []
    brands, refs = station["brand_hints"], station["possible_branch_references"]
    if len(brands) != 1 or len(refs) != 1:
        return "review_required", ["conflicting_or_missing_employer_identity"]
    if OPERATORS.get(brands[0]) != collector or p.get("@spider") != collector:
        return "rejected", ["source_namespace_mismatch"]
    if str(p.get("ref", "")) != refs[0]:
        return "rejected", ["branch_reference_mismatch"]
    if text_key(p.get("brand")) != text_key(brands[0]):
        reasons.append("brand_conflict_or_missing")
    if p.get("addr:country") != "US" or p.get("addr:state") != station["state"]:
        reasons.append("country_or_state_conflict_or_missing")
    if not p.get("addr:city") or text_key(p["addr:city"]) != text_key(station["city"]):
        reasons.append("locality_requires_additional_evidence")
    if not p.get("addr:street_address"):
        reasons.append("source_physical_address_missing")
    if p.get("amenity") != "fuel" and not (
        p.get("highway") == "services" and p.get("fuel:diesel") == "yes"
    ):
        reasons.append("fuel_facility_unconfirmed")
    if p.get("end_date"):
        reasons.append("closure_or_end_date_requires_review")
    if not str(p.get("@source_uri", "")).startswith("https://") or not feature.get("id"):
        reasons.append("source_provenance_missing")
    if coordinates(feature) is None:
        reasons.append("facility_coordinate_missing_or_invalid")
    return (
        ("review_required", reasons)
        if reasons
        else ("accepted", ["operator_branch_brand_state_locality_fuel_facility"])
    )


def match_sources(audit, manifest_path, validate_point):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_bytes())
    if not manifest.get("release") or not manifest.get("retrieved_at"):
        raise AuditError("ATP manifest needs a dated release and actual retrieval timestamp")
    indexed, source_counts = defaultdict(list), {}
    for source in manifest["sources"]:
        if source.get("status") != "available":
            continue
        raw = (manifest_path.parent / source["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise AuditError("ATP source file checksum mismatch")
        features = json.loads(raw).get("features", [])
        source_counts[source["collector"]] = len(features)
        if source["collector"] not in set(OPERATORS.values()):
            continue
        if not source.get("reference_semantics") or not source.get("coordinate_origin"):
            raise AuditError("Applicable ATP collector needs inspected source semantics")
        for feature in features:
            ref = str(feature.get("properties", {}).get("ref", ""))
            indexed[source["collector"], ref].append((source, feature))

    records, decisions = [], []
    for station in inventory(audit)["records"]:
        brands, refs = station["brand_hints"], station["possible_branch_references"]
        collector = OPERATORS.get(brands[0]) if len(brands) == 1 else None
        candidates = indexed.get((collector, refs[0]), []) if len(refs) == 1 else []
        status, reasons = "unresolved", ["no_supported_source_reference_candidate"]
        if not collector:
            reasons = ["operator_or_alias_requires_another_matching_path"]
        elif len(refs) != 1:
            status = "review_required" if refs else "unresolved"
            reasons = ["conflicting_branch_references" if refs else "branch_reference_missing"]
        elif len(candidates) > 1:
            status, reasons = "review_required", ["competing_source_features"]
        elif candidates:
            source, feature = candidates[0]
            status, reasons = match_feature(station, feature, collector)
            if status == "accepted" and not validate_point(coordinates(feature)):
                status, reasons = "review_required", ["source_coordinate_outside_supported_US"]
        evidence = {
            "identity_reason": reasons,
            "policy_version": VERSION,
            "retrieved_at": manifest["retrieved_at"],
            "release": manifest["release"],
        }
        if len(candidates) == 1:
            source, feature = candidates[0]
            evidence.update(
                source_url=source["url"],
                source_sha256=source["sha256"],
                feature_id=feature["id"],
                collector=collector,
                coordinate_origin=source["coordinate_origin"],
                reference_semantics=source["reference_semantics"],
                operator_location=feature,
                licence=source["licence"],
            )
        point = coordinates(candidates[0][1]) if status == "accepted" else None
        record = {
            "opis_id": station["opis_id"],
            "fingerprint": station["fingerprint"],
            "status": status,
            "source": "atp_published_operator" if candidates else "",
            "longitude": point[0] if point else None,
            "latitude": point[1] if point else None,
            "evidence": evidence,
        }
        records.append(record)
        decisions.append(
            {
                "opis_id": station["opis_id"],
                "name": station["name"],
                "state": station["state"],
                "city": station["city"],
                "collector": collector,
                "candidate_count": len(candidates),
                "status": status,
                "reasons": reasons,
                "candidate_ids": [f["id"] for _, f in candidates],
            }
        )

    collisions = defaultdict(list)
    for i, record in enumerate(records):
        if record["status"] == "accepted":
            collisions[record["longitude"], record["latitude"]].append(i)
    for indices in collisions.values():
        if len(indices) > 1:
            for i in indices:
                records[i].update(status="review_required", longitude=None, latitude=None)
                records[i]["evidence"]["identity_reason"] = [
                    "shared_coordinate_requires_identity_review"
                ]
                decisions[i].update(
                    status="review_required", reasons=["shared_coordinate_requires_identity_review"]
                )

    summary = {
        "identities": len(records),
        "candidate_identities": sum(d["candidate_count"] > 0 for d in decisions),
        "statuses": dict(Counter(r["status"] for r in records)),
        "source_feature_counts": source_counts,
        "accepted_by_state": dict(
            sorted(Counter(d["state"] for d in decisions if d["status"] == "accepted").items())
        ),
        "accepted_by_collector": dict(
            Counter(d["collector"] for d in decisions if d["status"] == "accepted")
        ),
        "reason_counts": dict(Counter(reason for d in decisions for reason in d["reasons"])),
    }
    artifact = {"source_sha256": audit.sha256, "version": VERSION, "records": records}
    report = {
        "source_sha256": audit.sha256,
        "version": VERSION,
        "summary": summary,
        "decisions": decisions,
    }
    return artifact, report
