import json

from django.core.management.base import BaseCommand, CommandError

from stations.ingestion import AuditError, audit_csv


class Command(BaseCommand):
    help = "Audit immutable fuel CSV and report deterministic counts and source hash."

    def add_arguments(self, parser):
        parser.add_argument("source")

    def handle(self, source, **options):
        try:
            audit = audit_csv(source)
        except (AuditError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps({"sha256": audit.sha256, **audit.summary}, indent=2))
