import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import django
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from planning import planner
from planning.domain import PlanError
from stations.enrichment import write_json
from stations.models import DatasetImport


class Command(BaseCommand):
    help = "Bounded live route evidence with repeated requests, timings and query counts; dry run by default."

    def add_arguments(self, parser):
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--routes", default="fixtures/benchmark-routes.json")
        parser.add_argument("--repetitions", type=int, default=2)
        parser.add_argument("--output", default="data/cache/benchmark.json")

    def handle(self, **options):
        routes = json.loads(Path(options["routes"]).read_text())
        if not 1 <= len(routes) <= 10 or not 1 <= options["repetitions"] <= 3:
            raise CommandError("Use 1–10 routes and 1–3 repetitions")
        self.stdout.write(
            f"Planned requests: {len(routes) * options['repetitions']}; max 3 outbound routing attempts per request."
        )
        if not options["live"]:
            return
        dataset = DatasetImport.objects.filter(is_active=True).first()
        rows = []
        original_route, original_candidates, original_solve = (
            planner.directions,
            planner.geometry.candidates,
            planner.solve,
        )
        for route in routes:
            for repetition in range(options["repetitions"]):
                timing = {}
                observed = {"routing_attempts_this_request": 0, "route_cache_hits": 0}

                def measured(label, function, timing=timing, observed=observed):
                    def wrapper(*args, **kwargs):
                        before = time.perf_counter()
                        try:
                            return function(*args, **kwargs)
                        finally:
                            timing[label] = (
                                timing.get(label, 0) + (time.perf_counter() - before) * 1000
                            )
                            if label == "routing_adapter_ms":
                                observed.update(
                                    routing_attempts_this_request=args[2].attempts,
                                    route_cache_hits=args[2].cache_hits,
                                )

                    return wrapper

                started = time.perf_counter()
                with (
                    CaptureQueriesContext(connection) as queries,
                    patch(
                        "planning.planner.directions",
                        side_effect=measured("routing_adapter_ms", original_route),
                    ),
                    patch(
                        "planning.planner.geometry.candidates",
                        side_effect=measured("candidate_projection_ms", original_candidates),
                    ),
                    patch(
                        "planning.planner.solve", side_effect=measured("solver_ms", original_solve)
                    ),
                ):
                    try:
                        result = planner.build_plan(route["start"], route["finish"])
                        row = {
                            "route": route["name"],
                            "repetition": repetition + 1,
                            "status": "success",
                            "diagnostics": result["diagnostics"],
                            "distance_miles": result["route"]["distance_miles"],
                            "purchases": len(result["fuel_stops"]),
                            "cost_usd": result["fuel"]["total_cost_usd"],
                            "map_url": result["map_url"],
                        }
                    except PlanError as exc:
                        row = {
                            "route": route["name"],
                            "repetition": repetition + 1,
                            "status": "failure",
                            "code": exc.code,
                            "message": exc.message,
                            "diagnostics": observed,
                        }
                row.update(
                    elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
                    db_queries=len(queries),
                    stage_ms={k: round(v, 3) for k, v in timing.items()},
                )
                rows.append(row)
                self.stdout.write(json.dumps(row))
        write_json(
            options["output"],
            {
                "measured_at": datetime.now(UTC).isoformat(),
                "python": platform.python_version(),
                "django": django.get_version(),
                "os": platform.system(),
                "dataset": str(dataset.id) if dataset else None,
                "accepted_station_count": dataset.stations.filter(
                    coordinate_status="accepted"
                ).count()
                if dataset
                else 0,
                "cache_context": "Existing local caches retained; inspect per-request hit flags. Local miss does not imply upstream provider cold.",
                "results": rows,
            },
        )
