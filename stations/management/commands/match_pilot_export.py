import hashlib
import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from planning.domain import PlanError
from planning.geography import validate_endpoint
from stations.enrichment import station_name, write_json
from stations.ingestion import audit_csv
from stations.operator_matching import VERSION, match_pilot


class Command(BaseCommand):
    help = (
        "Join a privately acquired official Pilot structured export to the supplied CSV, offline."
    )

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("directory")
        parser.add_argument("--retrieved-at", required=True)
        parser.add_argument("--output", default="data/enriched/pilot.json")

    def handle(self, source, directory, **options):
        retrieved = datetime.fromisoformat(options["retrieved_at"])
        if retrieved.utcoffset() is None:
            raise CommandError("retrieved-at must include a timezone")
        audit = audit_csv(source)
        raw = Path(directory).read_bytes()
        downloaded = json.loads(raw)
        entities = downloaded.get("entities", downloaded.get("response", {}).get("entities", []))
        if not entities:
            raise CommandError("Export must contain official location entities")
        by_number = {}
        for entity in entities:
            p = entity["profile"]
            number = str(p["meta"]["id"])
            if number in by_number:
                raise CommandError("Duplicate official store reference; do not mix snapshots")
            a, c = p["address"], p.get("yextDisplayCoordinate", {})
            by_number[number] = {
                "store_number": number,
                "name": p["name"],
                "country": a["countryCode"],
                "state": a["region"],
                "city": a["city"],
                "address": a["line1"],
                "latitude": c.get("lat"),
                "longitude": c.get("long"),
                "fuel_lanes": p.get("c_pagesFuelLaneCount"),
                "interstate": p.get("c_interstate"),
                "url": p.get("landingPageUrl"),
            }
        records = []
        for opis, station in audit.stations.items():
            _, number = station_name(station["fields"]["Truckstop Name"])
            location = by_number.get(number)
            status, reasons = (
                match_pilot(station["fields"], location)
                if location
                else ("unresolved", ["no_matching_official_store_reference"])
            )
            if status == "accepted":
                try:
                    validate_endpoint([location["longitude"], location["latitude"]])
                except PlanError as exc:
                    if exc.code == "DATA_NOT_READY":
                        raise CommandError(exc.message) from exc
                    status, reasons = (
                        "review_required",
                        ["official_coordinate_outside_supported_boundary"],
                    )
            records.append(
                {
                    "opis_id": opis,
                    "fingerprint": station["fingerprint"],
                    "status": status,
                    "source": "pilot_official_export" if location else "",
                    "latitude": location["latitude"] if status == "accepted" else None,
                    "longitude": location["longitude"] if status == "accepted" else None,
                    "evidence": {
                        "identity_reason": reasons,
                        "retrieved_at": retrieved.isoformat(),
                        "url": location.get("url") if location else None,
                        "official_location": location,
                        "directory_sha256": hashlib.sha256(raw).hexdigest(),
                        "policy_version": VERSION,
                    },
                }
            )
        write_json(
            options["output"],
            {"source_sha256": audit.sha256, "version": VERSION, "records": records},
        )
        counts = {
            s: sum(r["status"] == s for r in records)
            for s in ("accepted", "review_required", "unresolved", "rejected")
        }
        self.stdout.write(json.dumps({"directory_locations": len(entities), **counts}))
