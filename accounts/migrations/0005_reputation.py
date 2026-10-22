# Rename PointEvent -> ReputationEvent, points -> reputation,
# rename related_names, and add ReputationNetwork + network FK
# (design-for-extension: multiple reputation networks later).
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_delete_participantprofile'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='PointEvent',
            new_name='ReputationEvent',
        ),
        migrations.RenameField(
            model_name='reputationevent',
            old_name='points',
            new_name='reputation',
        ),
        migrations.AlterField(
            model_name='reputationevent',
            name='user',
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name='reputation_events',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='reputationevent',
            name='letter',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name='reputation_events',
                to='letters.letterinstance',
            ),
        ),
        migrations.CreateModel(
            name='ReputationNetwork',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.AddField(
            model_name='reputationevent',
            name='network',
            field=models.ForeignKey(
                blank=True,
                help_text='The reputation network this event belongs to (optional; supports multiple networks later).',
                null=True,
                on_delete=models.SET_NULL,
                related_name='events',
                to='accounts.reputationnetwork',
            ),
        ),
    ]
