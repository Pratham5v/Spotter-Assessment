import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from planning.domain import PlanError
from planning.geography import validate_endpoint
from stations.atp_matching import match_sources, reconcile_baseline
from stations.enrichment import load_artifact, write_json
from stations.ingestion import AuditError, audit_csv


class Command(BaseCommand):
    help = "Match inspected published ATP references offline; retain every unresolved identity."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("manifest")
        parser.add_argument("--output", default="data/enriched/atp-stations.json")
        parser.add_argument("--report", default="data/enriched/atp-decisions.json")
        parser.add_argument(
            "--baseline", help="Recheck an existing artifact without hiding new conflicts"
        )

    def handle(self, source, manifest, **options):
        def supported(point):
            try:
                validate_endpoint(point)
                return True
            except PlanError as exc:
                if exc.code == "DATA_NOT_READY":
                    raise CommandError(exc.message) from exc
                return False

        try:
            audit = audit_csv(source)
            artifact, report = match_sources(audit, manifest, supported)
            if options["baseline"]:
                _, baseline, baseline_hash = load_artifact(options["baseline"], audit)
                report["baseline_reconciliation"] = reconcile_baseline(
                    artifact, baseline, audit, supported
                )
                artifact["baseline_sha256"] = baseline_hash
                artifact["version"] += "_reconciled_v1"
                report["summary"]["accepted_after_reconciliation"] = sum(
                    r["status"] == "accepted" for r in artifact["records"]
                )
            report["summary"]["final_statuses"] = dict(
                Counter(r["status"] for r in artifact["records"])
            )
            report["summary"]["final_accepted_by_state"] = dict(
                sorted(
                    Counter(
                        audit.stations[r["opis_id"]]["fields"]["State"]
                        for r in artifact["records"]
                        if r["status"] == "accepted"
                    ).items()
                )
            )
            write_json(options["output"], artifact)
            write_json(options["report"], report)
        except (AuditError, OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report["summary"], indent=2))
