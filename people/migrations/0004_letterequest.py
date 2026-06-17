from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('people', '0003_person_email'),
    ]

    operations = [
        migrations.CreateModel(
            name='LetterRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nickname', models.CharField(max_length=255)),
                ('pirate_address', models.CharField(
                    blank=True, max_length=255,
                    help_text='Social handle, venue, bar, camp, regular haunt — NOT a postal address.',
                )),
                ('city',   models.CharField(blank=True, max_length=255)),
                ('state',  models.CharField(blank=True, max_length=255)),
                ('region', models.CharField(blank=True, max_length=255)),
                ('write_about', models.TextField(
                    blank=True,
                    help_text='What the writer should address. Becomes the prompt in the write queue.',
                )),
                ('status', models.CharField(
                    choices=[
                        ('pending',    'Pending — waiting to be written'),
                        ('written',    'Written — letter exists, not yet printed'),
                        ('in_transit', 'In Transit — physically moving'),
                        ('delivered',  'Delivered'),
                        ('archived',   'Archived'),
                    ],
                    default='pending', max_length=32,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
