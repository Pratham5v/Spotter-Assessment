"""Explicit offline demonstration; rolls back DB state and uses a temporary cache."""

import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings

from planning.domain import StationOccurrence
from planning.fuel import METRES_PER_MILE
from planning.planner import build_plan
from stations.artifacts import write_json
from stations.importing import import_snapshot
from stations.ingestion import audit_csv


class Command(BaseCommand):
    help = (
        "Produce a labeled synthetic plan with zero external requests; leave active data untouched."
    )

    def handle(self, **options):
        source = settings.BASE_DIR / "fixtures/synthetic-fuel.csv"
        audit = audit_csv(source)
        identity = audit.stations["SYN001"]
        with (
            tempfile.TemporaryDirectory() as directory,
            transaction.atomic(),
            override_settings(
                CACHES={
                    "default": {
                        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                        "LOCATION": "synthetic-demo",
                    }
                }
            ),
        ):
            artifact = Path(directory) / "synthetic.json"
            write_json(
                artifact,
                {
                    "source_sha256": audit.sha256,
                    "version": "synthetic_demo_v1",
                    "records": [
                        {
                            "opis_id": "SYN001",
                            "fingerprint": identity["fingerprint"],
                            "status": "accepted",
                            "latitude": 35.0,
                            "longitude": -94.0,
                            "source": "synthetic",
                            "evidence": {
                                "identity_reason": "authored synthetic fixture",
                                "retrieved_at": "2000-01-01T00:00:00Z",
                            },
                        }
                    ],
                },
            )
            dataset, _ = import_snapshot(source, artifact)
            station = dataset.stations.values().get()
            candidate = {
                "station": station,
                "offset_m": 0,
                "occurrence": StationOccurrence(
                    "SYN001:0", "SYN001", Decimal(400) * METRES_PER_MILE, station["price"]
                ),
            }

            def simulated_route(points, radiuses, budget):
                legs = [900] if len(points) == 2 else [400, 500]
                return {
                    "geometry": {"type": "LineString", "coordinates": points},
                    "distance_m": str(Decimal(900) * METRES_PER_MILE),
                    "duration_seconds": 100,
                    "legs_m": [str(Decimal(m) * METRES_PER_MILE) for m in legs],
                    "snapped": points,
                    "snap_distances_m": [0] * len(points),
                    "warnings": [],
                }

            with (
                patch("planning.planner.validate_endpoint", return_value="synthetic_boundary"),
                patch("planning.planner.geometry.candidates", return_value=[candidate]),
                patch("planning.planner.directions", side_effect=simulated_route),
            ):
                result = build_plan([-100, 35], [-84, 35])
            result["demonstration"] = {
                "synthetic": True,
                "actual_external_requests": 0,
                "geometry_and_distances": "authored illustrative fixture; not a verified road route",
                "map_url": "temporary cache; not served by the web process",
            }
            result["provenance"].update(provider="synthetic", profile="synthetic")
            transaction.set_rollback(True)
            self.stdout.write(json.dumps(result, indent=2))
