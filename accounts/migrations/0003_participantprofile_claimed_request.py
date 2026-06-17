# accounts/migrations/0003_participantprofile_claimed_request.py
#
# Replaces the old people.Person FK (claimed_person) with a people.LetterRequest FK
# (claimed_request). The old column is dropped; it had no data worth preserving.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_participantprofile'),
        ('people',   '0004_letterequest'),
    ]

    operations = [
        # Drop the old FK that pointed at the now-deleted people.Person table
        migrations.RemoveField(
            model_name='participantprofile',
            name='claimed_person',
        ),
        # Add the replacement FK pointing at LetterRequest
        migrations.AddField(
            model_name='participantprofile',
            name='claimed_request',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='profiles',
                to='people.letterrequest',
                help_text='The letter request this account is associated with, if any.',
            ),
        ),
    ]
