# letters/migrations/0004_letterhop_letterinstance_refactor.py
#
# SUPERSEDED — this migration was created by a previous push but conflicts with
# the existing 0004/0005 migrations already in the database.
# It is replaced by 0006_add_request_and_written_by.py
# This file is intentionally a no-op so Django can track it without erroring.

from django.db import migrations


class Migration(migrations.Migration):
    """
    No-op placeholder. The real work is in 0006_add_request_and_written_by.
    """

    dependencies = [
        ('letters', '0005_letterhop'),
        ('people',  '0004_letterequest'),
    ]

    operations = []
