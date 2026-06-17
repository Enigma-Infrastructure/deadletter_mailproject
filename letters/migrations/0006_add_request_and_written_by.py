# letters/migrations/0006_add_request_and_written_by.py
#
# Adds the `request` FK and `written_by` FK to LetterInstance.
# Both are nullable so existing letter rows are unaffected.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('letters', '0004_letterhop_letterinstance_refactor'),
        ('people',  '0004_letterequest'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='letterinstance',
            name='request',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='instances',
                to='people.letterrequest',
                help_text='The letter request this was written in response to.',
            ),
        ),
        migrations.AddField(
            model_name='letterinstance',
            name='written_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='letters_written',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
