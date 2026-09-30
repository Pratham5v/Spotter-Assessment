import json

from django.core.management.base import BaseCommand, CommandError

from stations.importing import import_snapshot
from stations.ingestion import AuditError


class Command(BaseCommand):
    help = "Atomically import and activate a validated immutable snapshot."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("enrichment")

    def handle(self, source, enrichment, **options):
        try:
            dataset, created = import_snapshot(source, enrichment)
        except (AuditError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            json.dumps(
                {"dataset": str(dataset.id), "created": created, **dataset.summary}, indent=2
            )
        )
