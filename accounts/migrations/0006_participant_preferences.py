from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_reputation")]

    operations = [
        migrations.CreateModel(
            name="RegistrationSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=64, unique=True)),
                ("label", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.AddField(
            model_name="user", name="participant_status",
            field=models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("suspended", "Suspended")], default="pending", max_length=16),
        ),
        migrations.AddField(
            model_name="user", name="default_request_visibility",
            field=models.CharField(choices=[("public", "Public"), ("participants_only", "Participants only")], default="public", max_length=24),
        ),
        migrations.AddField(
            model_name="user", name="default_body_visibility",
            field=models.CharField(choices=[("public", "Public"), ("participants_only", "Participants only")], default="public", max_length=24),
        ),
        migrations.AddField(
            model_name="user", name="registration_source",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="registrations", to="accounts.registrationsource"),
        ),
        migrations.AddField(
            model_name="user", name="participant_reviewed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="participant_reviews", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="user", name="participant_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
