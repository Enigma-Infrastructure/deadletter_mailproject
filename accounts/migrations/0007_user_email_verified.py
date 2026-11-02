from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0006_participant_preferences')]
    operations = [
        migrations.AddField(
            model_name='user', name='email_verified',
            field=models.BooleanField(default=False, editable=False, verbose_name='Email verified'),
        ),
    ]
