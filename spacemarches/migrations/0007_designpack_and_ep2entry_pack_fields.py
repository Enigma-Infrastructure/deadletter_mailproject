import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


STORYTELLER_PACK_SLUGS = {"creatures", "psi-epsilon-sleights"}

CANONICAL_PACKS = [
    {
        "slug": "ep-crb",
        "name": "EP2e CRB",
        "description": (
            "Player-facing morphs, gear, augmentations, traits, psi sleights, and substances "
            "from the Eclipse Phase 2nd Edition Core Rulebook."
        ),
        "tier": "crb",
        "is_storyteller_only": False,
        "is_official": True,
        "is_public": True,
        "is_active": True,
        "source_url": "https://github.com/Bubz43/ep2e",
        "metadata": {"dependency_ids": []},
    },
    {
        "slug": "ep-crb-storyteller",
        "name": "EP2e CRB (Storyteller)",
        "description": (
            "Threats, creatures, epsilon sleights, and Storyteller-only material from the "
            "Eclipse Phase 2nd Edition Core Rulebook."
        ),
        "tier": "crb_storyteller",
        "is_storyteller_only": True,
        "is_official": True,
        "is_public": True,
        "is_active": True,
        "source_url": "https://github.com/Bubz43/ep2e",
        "metadata": {"dependency_ids": ["ep-crb"]},
    },
    {
        "slug": "ep-copt",
        "name": "EP2e Character Options",
        "description": (
            "Expanded morphs, traits, augmentations, and Life-Path options from Eclipse Phase "
            "2e Character Options (staged for Compendium import)."
        ),
        "tier": "copt",
        "is_storyteller_only": False,
        "is_official": True,
        "is_public": True,
        "is_active": True,
        "source_url": "https://github.com/TheGam1ngWizard/ep2e-virtual",
        "metadata": {"dependency_ids": ["ep-crb"], "status": "queued_import"},
    },
    {
        "slug": "spacemarches",
        "name": "Spacemarches",
        "description": (
            "Official Spacemarches campaign pack for custom setting gear, morph variants, "
            "traits, and homebrew additions."
        ),
        "tier": "spacemarches",
        "is_storyteller_only": False,
        "is_official": True,
        "is_public": True,
        "is_active": True,
        "source_url": "",
        "metadata": {"dependency_ids": ["ep-crb"]},
    },
]


def seed_initial_design_packs(apps, schema_editor):
    DesignPack = apps.get_model("spacemarches", "DesignPack")
    Ep2Entry = apps.get_model("spacemarches", "Ep2Entry")

    packs_by_slug = {}
    for spec in CANONICAL_PACKS:
        pack_obj, _ = DesignPack.objects.update_or_create(
            slug=spec["slug"],
            defaults=spec,
        )
        packs_by_slug[spec["slug"]] = pack_obj

    crb_pack = packs_by_slug["ep-crb"]
    st_pack = packs_by_slug["ep-crb-storyteller"]

    for entry in Ep2Entry.objects.filter(design_pack__isnull=True):
        sys_data = entry.system if isinstance(entry.system, dict) else {}
        is_st = entry.pack in STORYTELLER_PACK_SLUGS or bool(sys_data.get("isGamemasterOnly"))
        entry.design_pack = st_pack if is_st else crb_pack
        entry.is_storyteller_only = is_st
        entry.save(update_fields=["design_pack", "is_storyteller_only"])


class Migration(migrations.Migration):

    dependencies = [
        ("spacemarches", "0006_ep2entry"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DesignPack",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "tier",
                    models.CharField(
                        choices=[
                            ("crb", "EP2e Core Rulebook"),
                            ("crb_storyteller", "EP2e CRB (Storyteller)"),
                            ("copt", "EP2e Character Options"),
                            ("spacemarches", "Spacemarches Official"),
                            ("custom", "Custom Pack"),
                        ],
                        default="custom",
                        max_length=24,
                    ),
                ),
                ("is_storyteller_only", models.BooleanField(default=False)),
                ("is_official", models.BooleanField(default=False)),
                ("is_public", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(default=True)),
                ("source_url", models.URLField(blank=True, default="")),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="design_packs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-is_official", "tier", "name"],
            },
        ),
        migrations.AddField(
            model_name="ep2entry",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="custom_ep2_entries",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="ep2entry",
            name="design_pack",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="entries",
                to="spacemarches.designpack",
            ),
        ),
        migrations.AddField(
            model_name="ep2entry",
            name="is_custom",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="ep2entry",
            name="is_storyteller_only",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="ep2entry",
            index=models.Index(fields=["is_storyteller_only"], name="sm_ep2_st_idx"),
        ),
        migrations.AddIndex(
            model_name="ep2entry",
            index=models.Index(fields=["is_custom"], name="sm_ep2_custom_idx"),
        ),
        migrations.RunPython(seed_initial_design_packs, migrations.RunPython.noop),
    ]
