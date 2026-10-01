import hashlib
import json

from django.db import transaction
from django.utils import timezone

from stations.artifacts import load_artifact
from stations.ingestion import NORMALIZATION, PRICE_POLICY, audit_csv
from stations.models import DatasetImport, PriceObservation, Station


def import_snapshot(source, enrichment):
    audit = audit_csv(source)
    artifact, records, enrichment_hash = load_artifact(enrichment, audit)
    fingerprint = hashlib.sha256(
        json.dumps(
            [audit.sha256, enrichment_hash, PRICE_POLICY, NORMALIZATION, artifact["version"]]
        ).encode()
    ).hexdigest()
    with transaction.atomic():
        # Serialize imports across workers, including an initially empty database.
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [60260930])
        existing = DatasetImport.objects.filter(fingerprint=fingerprint, status="complete").first()
        if existing:
            return existing, False
        dataset = DatasetImport.objects.create(
            source_label="assessment CSV",
            source_sha256=audit.sha256,
            enrichment_sha256=enrichment_hash,
            fingerprint=fingerprint,
            price_policy=PRICE_POLICY,
            normalization_version=NORMALIZATION,
            enrichment_version=artifact["version"],
            summary=audit.summary,
        )
        stations = []
        for opis_id, source_station in audit.stations.items():
            fields, record = source_station["fields"], records.get(opis_id, {})
            accepted = record.get("status") == "accepted"
            stations.append(
                Station(
                    dataset=dataset,
                    opis_id=opis_id,
                    name=fields["Truckstop Name"],
                    aliases=source_station["aliases"],
                    address=fields["Address"],
                    city=fields["City"],
                    state=fields["State"],
                    price=source_station["price"],
                    min_price=source_station["min_price"],
                    max_price=source_station["max_price"],
                    observation_count=len(source_station["observations"]),
                    distinct_price_count=source_station["distinct_prices"],
                    location_fingerprint=source_station["fingerprint"],
                    coordinate_status=record.get("status", "unresolved"),
                    coordinate_source=record.get("source", ""),
                    latitude=record.get("latitude") if accepted else None,
                    longitude=record.get("longitude") if accepted else None,
                    location_evidence=record.get("evidence", {}),
                )
            )
        Station.objects.bulk_create(stations, batch_size=1000)
        by_id = {s.opis_id: s for s in stations}
        PriceObservation.objects.bulk_create(
            [
                PriceObservation(
                    dataset=dataset,
                    station=by_id.get(r.fields["OPIS Truckstop ID"])
                    if r.classification == "US"
                    else None,
                    source_row_number=r.number,
                    opis_id=r.fields["OPIS Truckstop ID"],
                    rack_id=r.fields["Rack ID"],
                    price=r.price,
                    raw=r.raw,
                    classification=r.classification,
                )
                for r in audit.rows
            ],
            batch_size=1000,
        )
        summary = {
            **audit.summary,
            "accepted_coordinates": sum(s.coordinate_status == "accepted" for s in stations),
        }
        dataset.summary, dataset.status, dataset.completed_at = summary, "complete", timezone.now()
        DatasetImport.objects.filter(is_active=True).update(is_active=False)
        dataset.is_active = True
        dataset.save()
        return dataset, True
