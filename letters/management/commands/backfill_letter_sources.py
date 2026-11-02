import json

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connections
from letters.source_backfill import BackfillConflict, backfill_sources


class Command(BaseCommand):
    help = 'Preview historical request/letter conversion; --apply writes in one transaction. Stop all writers first.'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--database', default='default', choices=tuple(connections))
        parser.add_argument('--apply', action='store_true', help='Create new records and link previously unlinked instances.')

    def handle(self, *args, **options):
        try:
            report = backfill_sources(using=options['database'], apply=options['apply'])
        except BackfillConflict as error:
            raise CommandError(str(error)) from None
        except DatabaseError:
            raise CommandError('Database conversion failed. No conversion was committed. Check schema/access and review conflicts before retrying.') from None
        report['mode'] = 'applied' if options['apply'] else 'preview'
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
