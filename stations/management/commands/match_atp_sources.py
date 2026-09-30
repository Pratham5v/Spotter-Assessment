import json

from django.core.management.base import BaseCommand, CommandError

from planning.domain import PlanError
from planning.geography import validate_endpoint
from stations.atp_matching import match_sources
from stations.enrichment import write_json
from stations.ingestion import AuditError, audit_csv


class Command(BaseCommand):
    help = "Match inspected published ATP references offline; retain every unresolved identity."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("manifest")
        parser.add_argument("--output", default="data/enriched/atp-stations.json")
        parser.add_argument("--report", default="data/enriched/atp-decisions.json")

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
            artifact, report = match_sources(audit_csv(source), manifest, supported)
            write_json(options["output"], artifact)
            write_json(options["report"], report)
        except (AuditError, OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report["summary"], indent=2))
