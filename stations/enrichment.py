"""Coordinate evidence contracts and conservative identity matching."""

import hashlib
import json
import math
import re
from pathlib import Path

from stations.ingestion import AuditError

VERSION = "identity_evidence_v1"
BRANDS = [
    ("FLYING J", "Flying J"),
    ("PILOT", "Pilot"),
    ("LOVES", "Love's"),
    ("CASEYS", "Casey's"),
    ("ROAD RANGER", "Road Ranger"),
    ("7ELEVEN", "7-Eleven"),
    ("CIRCLE K", "Circle K"),
    ("ALLSUPS", "Allsup's"),
]


def words(text):
    return re.sub(r"[^a-z0-9 ]", "", text.casefold())


def station_name(name):
    clean = words(name).upper()
    brand = next(
        (replacement for token, replacement in BRANDS if token in clean),
        re.sub(r"\s*#.*$", "", name).strip(),
    )
    number = re.search(r"#\s*(\d+)", name)
    return brand, number.group(1) if number else None


def match_candidate(fields, feature):
    brand, number = station_name(fields["Truckstop Name"])
    reasons = []
    if feature.get("country_code") != "us" or feature.get("state_code") != fields["State"]:
        return "rejected", ["country_or_state_mismatch"]
    if feature.get("result_type") not in ("amenity", "building"):
        return "rejected", ["not_a_facility"]
    if feature.get("category") != "service.vehicle.fuel":
        reasons.append("fuel_identity_unconfirmed")
    name_match = words(brand) in words(feature.get("name") or "")
    if not name_match:
        reasons.append("name_mismatch")
    # A provider confidence number is not branch evidence.
    reference = str(feature.get("store_ref") or "")
    store_match = bool(number and reference == number)
    address = fields["Address"]
    numbered = re.match(r"^(\d+)\s+(.+)$", address) if "exit" not in address.casefold() else None
    exact_address = bool(
        numbered
        and feature.get("housenumber") == numbered.group(1)
        and words(feature.get("street") or "") == words(numbered.group(2))
        and words(feature.get("city") or "") == words(fields["City"])
    )
    if store_match or exact_address:
        if not reasons and feature.get("result_type") == "amenity":
            return "accepted", [
                "fuel_poi",
                "store_reference_match" if store_match else "exact_number_street_locality",
            ]
    reasons.append("branch_or_address_evidence_required")
    return "review_required", reasons


def load_artifact(path, audit):
    raw = Path(path).read_bytes()
    artifact = json.loads(raw)
    if artifact.get("source_sha256") != audit.sha256 or not artifact.get("version"):
        raise AuditError("Enrichment artifact source/version mismatch")
    records, seen = {}, set()
    for record in artifact.get("records", []):
        opis_id = str(record["opis_id"])
        if opis_id in seen or opis_id not in audit.stations:
            raise AuditError("Duplicate or unknown enrichment identity")
        seen.add(opis_id)
        if record.get("fingerprint") != audit.stations[opis_id]["fingerprint"]:
            raise AuditError(f"Stale enrichment identity: {opis_id}")
        if record.get("status") not in ("accepted", "review_required", "unresolved", "rejected"):
            raise AuditError("Unknown coordinate status")
        if record["status"] == "accepted":
            lat, lon = record.get("latitude"), record.get("longitude")
            if (
                isinstance(lat, bool)
                or isinstance(lon, bool)
                or not isinstance(lat, (float, int))
                or not isinstance(lon, (float, int))
                or not math.isfinite(lat)
                or not math.isfinite(lon)
                or not -90 <= lat <= 90
                or not -180 <= lon <= 180
            ):
                raise AuditError("Accepted coordinates must be finite and in range")
            evidence = record.get("evidence", {})
            if (
                not record.get("source")
                or not evidence.get("identity_reason")
                or not evidence.get("retrieved_at")
            ):
                raise AuditError("Accepted coordinates require identity provenance")
            if record.get("source") == "official_review" and not (
                evidence.get("url", "").startswith("https://") and evidence.get("reviewer")
            ):
                raise AuditError("Official override requires source URL and reviewer")
        records[opis_id] = record
    return artifact, records, hashlib.sha256(raw).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
