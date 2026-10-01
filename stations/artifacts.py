"""Validation and atomic writing of prepared coordinate artifacts."""

import hashlib
import json
import math
from pathlib import Path

from stations.ingestion import AuditError


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
