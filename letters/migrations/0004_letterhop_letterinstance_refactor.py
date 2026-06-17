from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import letters.models


class Migration(migrations.Migration):
    """
    - Adds LetterHop table (was defined in models but never migrated)
    - Removes old LetterConcept-related fields from LetterInstance
    - Adds request FK to LetterInstance pointing at people.LetterRequest
    - Removes LetterConcept table
    """

    dependencies = [
        ('letters', '0003_auto_20250529_1200'),
        ('people',  '0004_letterequest'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Create LetterHop
        migrations.CreateModel(
            name='LetterHop',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[
                        ('waiting',          'Waiting to be carried'),
                        ('picked_up',        'Picked up by carrier'),
                        ('in_transit',       'In transit'),
                        ('left_at_location', 'Left at location'),
                        ('delivered',        'Delivered to recipient'),
                        ('archived',         'Archived'),
                    ],
                    default='waiting', max_length=20,
                )),
                ('city',       models.CharField(blank=True, max_length=100)),
                ('region',     models.CharField(blank=True, max_length=100)),
                ('venue_hint', models.CharField(blank=True, max_length=255)),
                ('notes',      models.TextField(blank=True)),
                ('image',      models.ImageField(blank=True, upload_to='letter_hops/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('letter', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='hops',
                    to='letters.letterinstance',
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-created_at']},
        ),

        # 2. Add request FK to LetterInstance (nullable so existing rows survive)
        migrations.AddField(
            model_name='letterinstance',
            name='request',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='instances',
                to='people.letterrequest',
                help_text='The letter request this was written in response to.',
            ),
        ),

        # 3. Add written_by to LetterInstance
        migrations.AddField(
            model_name='letterinstance',
            name='written_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='letters_written',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
