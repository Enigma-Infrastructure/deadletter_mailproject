from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('letters', '0009_auto_20260928_1638'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='LetterRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('prompt', models.TextField(blank=True)),
                ('recipient_alias', models.CharField(blank=True, max_length=255)),
                ('destination_city', models.CharField(blank=True, max_length=255)),
                ('destination_label', models.CharField(blank=True, max_length=1024)),
                ('requested_visibility', models.CharField(choices=[('public', 'Public'), ('participants_only', 'Participants only')], default='participants_only', max_length=24)),
                ('automatically_restricted', models.BooleanField(default=False, editable=False)),
                ('restriction_reason', models.CharField(blank=True, editable=False, max_length=255)),
                ('is_published', models.BooleanField(default=False, editable=False)),
                ('is_open', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('recipient', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='letter_requests', to='people.person')),
                ('destination_place', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='letter_requests', to='people.place')),
                ('concept', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='linked_requests', to='letters.letterconcept')),
                ('legacy_source', models.OneToOneField(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='migrated_request', to='letters.letterconcept')),
                ('submitted_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='letter_requests_submitted', to=settings.AUTH_USER_MODEL)),
                ('owner', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='letter_requests_owned', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at'], 'constraints': [models.CheckConstraint(condition=models.Q(requested_visibility__in=['public', 'participants_only']), name='letter_req_visibility_valid')]},
        ),
        migrations.CreateModel(
            name='Letter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body_text', models.TextField(blank=True)),
                ('prompt_snapshot', models.TextField(blank=True)),
                ('recipient_alias', models.CharField(blank=True, max_length=255)),
                ('destination_city', models.CharField(blank=True, max_length=255)),
                ('destination_label', models.CharField(blank=True, max_length=1024)),
                ('requested_visibility', models.CharField(choices=[('public', 'Public'), ('participants_only', 'Participants only')], default='participants_only', max_length=24)),
                ('automatically_restricted', models.BooleanField(default=False, editable=False)),
                ('restriction_reason', models.CharField(blank=True, editable=False, max_length=255)),
                ('is_published', models.BooleanField(default=False, editable=False)),
                ('finalized_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('request', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='responses', to='letters.letterrequest')),
                ('concept', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='authored_letters', to='letters.letterconcept')),
                ('writer', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='letters_written', to=settings.AUTH_USER_MODEL)),
                ('recipient', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='authored_letters', to='people.person')),
                ('destination_place', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='authored_letters', to='people.place')),
            ],
            options={'ordering': ['-created_at'], 'constraints': [models.CheckConstraint(condition=models.Q(requested_visibility__in=['public', 'participants_only']), name='auth_letter_visibility_valid')]},
        ),
        migrations.AddField(
            model_name='letterinstance', name='authored_letter',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='instances', to='letters.letter'),
        ),
    ]
