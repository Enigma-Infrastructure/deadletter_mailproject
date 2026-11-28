# Generated manually for EP2e Life Path database models

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("spacemarches", "0010_eclipsephasecensus"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LifepathTable",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=80, unique=True)),
                (
                    "step_number",
                    models.PositiveSmallIntegerField(
                        db_index=True,
                        default=0,
                        help_text="Life Path step (1-15), or 0 for Reference / Gear Pack tables.",
                    ),
                ),
                ("code", models.CharField(blank=True, default="", max_length=32)),
                ("name", models.CharField(max_length=160)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("package", "Package / Path Selection"),
                            ("event", "Life / Campaign Event"),
                            ("subtable", "Sub-Background / Sub-Career Table"),
                            ("reference", "Reference Roll Table"),
                            ("gear_pack", "Starting Gear Pack"),
                        ],
                        default="event",
                        max_length=24,
                    ),
                ),
                (
                    "die_type",
                    models.CharField(
                        choices=[
                            ("d10", "1d10 (1-0)"),
                            ("d100", "1d100 (00-99)"),
                            ("d10_pair", "1d10 #1 + 1d10 #2"),
                            ("choice", "Player Choice"),
                            ("fixed", "Fixed / Package"),
                            ("d6", "1d6"),
                        ],
                        default="d100",
                        max_length=16,
                    ),
                ),
                ("description", models.TextField(blank=True, default="")),
                (
                    "allow_choice",
                    models.BooleanField(
                        default=True,
                        help_text="Whether players may pick an entry directly instead of rolling.",
                    ),
                ),
                ("rules_meta", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                (
                    "is_custom",
                    models.BooleanField(
                        default=False,
                        help_text="Mark custom to protect Storyteller edits during re-seeding.",
                    ),
                ),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["step_number", "sort_order", "name"],
                "indexes": [
                    models.Index(fields=["step_number", "category"], name="sm_lp_tbl_step_cat_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="LifepathEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=64)),
                ("roll_min", models.IntegerField(blank=True, db_index=True, null=True)),
                ("roll_max", models.IntegerField(blank=True, db_index=True, null=True)),
                ("sub_roll_min", models.IntegerField(blank=True, null=True)),
                ("sub_roll_max", models.IntegerField(blank=True, null=True)),
                ("title", models.CharField(max_length=255)),
                ("summary", models.TextField(blank=True, default="")),
                (
                    "next_table_slug",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Optional table slug triggered directly after selecting/rolling this row.",
                        max_length=80,
                    ),
                ),
                (
                    "effects",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Structured mechanical effects JSON (aptitudes, skills, rep, traits, flex, morph, choices, sub_rolls, gear, flags).",
                    ),
                ),
                ("raw_source", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                (
                    "is_custom",
                    models.BooleanField(
                        default=False,
                        help_text="Mark custom to protect Storyteller edits during re-seeding.",
                    ),
                ),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "table",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="spacemarches.lifepathtable",
                    ),
                ),
            ],
            options={
                "ordering": ["table", "sort_order", "roll_min", "sub_roll_min", "title"],
                "unique_together": {("table", "code")},
                "indexes": [
                    models.Index(fields=["table", "is_active", "roll_min", "roll_max"], name="sm_lp_entry_roll_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="LifepathSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("discord_user_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("discord_channel_id", models.CharField(blank=True, default="", max_length=64)),
                ("discord_message_id", models.CharField(blank=True, default="", max_length=64)),
                ("character_name", models.CharField(default="Unnamed Lifepath Ego", max_length=160)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("in_progress", "In Progress"),
                            ("completed", "Completed"),
                            ("archived", "Archived"),
                        ],
                        db_index=True,
                        default="in_progress",
                        max_length=20,
                    ),
                ),
                ("current_step", models.PositiveSmallIntegerField(default=1)),
                (
                    "hardcore_flex",
                    models.BooleanField(
                        default=False,
                        help_text="If enabled, spending Flex to reroll permanently reduces final starting Flex.",
                    ),
                ),
                ("state", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "dossier",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lifepath_sessions",
                        to="spacemarches.characterdossier",
                    ),
                ),
                (
                    "generated_character",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lifepath_sessions",
                        to="spacemarches.generatedcharacter",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lifepath_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
    ]
