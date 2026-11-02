import json

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections
from letters.source_audit import collect_audit


class Command(BaseCommand):
    help = 'Read-only aggregate inventory for the request/letter backfill; no private values or IDs.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--database', default='default', choices=tuple(connections))
        parser.add_argument('--json', action='store_true', dest='as_json', help='Emit only a versioned JSON count report.')

    def handle(self, *args, **options):
        try:
            report = collect_audit(using=options['database'])
        except DatabaseError:
            raise CommandError('Audit could not read the expected schema. Check database access and applied migrations; no backfill was attempted.') from None
        if options['as_json']:
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
            return
        self.stdout.write('Letter source audit: aggregate counts only; no classification or writes.')
        self.stdout.write('Report schema version: ' + str(report['schema_version']))
        for section, counts in report.items():
            if section == 'schema_version':
                continue
            self.stdout.write(section + ':')
            for key, value in sorted(counts.items()):
                self.stdout.write(f'  {key}: {value}')
