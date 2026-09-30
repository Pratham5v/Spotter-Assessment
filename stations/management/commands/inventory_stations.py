import json

from django.core.management.base import BaseCommand, CommandError

from stations.enrichment import write_json
from stations.ingestion import AuditError, audit_csv
from stations.inventory import inventory


class Command(BaseCommand):
    help = "Inventory every US employer identity offline, preserving aliases and search hints."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--output", default="data/enriched/station-inventory.json")

    def handle(self, source, **options):
        try:
            result = inventory(audit_csv(source))
            write_json(options["output"], result)
        except (AuditError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result["summary"], indent=2))
