from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('letters', '0010_request_letter_foundation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='DomainSubmissionReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('operation', models.CharField(choices=[('request', 'Request'), ('response', 'Response')], max_length=16)),
                ('key_digest', models.CharField(max_length=64)),
                ('payload_digest', models.CharField(max_length=64)),
                ('completed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='domain_submission_receipts', to=settings.AUTH_USER_MODEL)),
                ('request_result', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='letters.letterrequest')),
                ('letter_result', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='letters.letter')),
                ('instance_result', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='letters.letterinstance')),
            ],
            options={'constraints': [
                models.UniqueConstraint(fields=('actor', 'operation', 'key_digest'), name='domain_submission_actor_op_key'),
                models.CheckConstraint(condition=models.Q(operation__in=['request', 'response']), name='domain_submission_operation_valid'),
            ]},
        ),
    ]
