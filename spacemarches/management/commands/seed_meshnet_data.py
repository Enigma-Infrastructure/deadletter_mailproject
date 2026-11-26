"""Idempotently load the MeshNet-native design pack data into Ep2Entry.

Source: spacemarches/fixtures/meshnet-pack-designs.json — plain-English export of the
embedded design packs (ep-crb, ep-crb-gm / epsilon-sleights storyteller pack) from the
mesh-net fork (TheGam1ngWizard/mesh-net, CC BY 4.0 lineage from Bubz43/ep2e).

Rows are created/updated keyed by entry_id (pack:design_type:key). ep-copt (Character
Options) is deliberately NOT imported: it ships templated and must not be filled.
Safe to re-run. No deletes.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from spacemarches.models import Ep2Entry
from spacemarches.services.design_pack_service import ensure_canonical_design_packs

FIXTURE_RELATIVE = "fixtures/meshnet-pack-designs.json"

# MeshNet design types whose category is already represented in the compendium
# map onto the existing category; MeshNet-native-only types get new categories.
DESIGN_TYPE_TO_CATEGORY = {
    "activeSkill": Ep2Entry.CATEGORY_SKILL,
    "knowSkill": Ep2Entry.CATEGORY_KNOW_SKILL,
    "ego": Ep2Entry.CATEGORY_EGO,
    "skillPack": Ep2Entry.CATEGORY_SKILL_PACK,
    "rep": Ep2Entry.CATEGORY_REP,
    "movement": Ep2Entry.CATEGORY_MOVEMENT,
    "environment": Ep2Entry.CATEGORY_ENVIRONMENT,
    "successTestModifier": Ep2Entry.CATEGORY_MODIFIER,
    "weaponAccessory": Ep2Entry.CATEGORY_WEAPON_ACCESSORY,
    "ability": Ep2Entry.CATEGORY_ABILITY,
    # Overlapping types: MeshNet-native rows sit alongside the Bubz baseline in the
    # same category; display dedups by name in the bundle/Codex.
    "kineticAmmo": Ep2Entry.CATEGORY_GEAR,
    "beamWeapon": Ep2Entry.CATEGORY_GEAR,
    "service": Ep2Entry.CATEGORY_GEAR,
    "software": Ep2Entry.CATEGORY_GEAR,
    "chemical": Ep2Entry.CATEGORY_SUBSTANCE,
    "toxin": Ep2Entry.CATEGORY_SUBSTANCE,
    "chiSleight": Ep2Entry.CATEGORY_SLEIGHT,
    "gammaSleight": Ep2Entry.CATEGORY_SLEIGHT,
    "epsilonSleight": Ep2Entry.CATEGORY_SLEIGHT,
    "exovirusSubstrain": Ep2Entry.CATEGORY_SPECIAL,
    "digitalForm": Ep2Entry.CATEGORY_MORPH,
    "trait": Ep2Entry.CATEGORY_TRAIT,
    "character": Ep2Entry.CATEGORY_CHARACTER,
}

STORYTELLER_DESIGN_PACK = "ep-crb-storyteller"
CANONICAL_DESIGN_PACK_SLUG = {"ep-crb": "ep-crb", "ep-crb-gm": STORYTELLER_DESIGN_PACK}


class Command(BaseCommand):
    help = (
        "Seed Ep2Entry with the MeshNet-native design pack data (idempotent). "
        "Skips ep-copt (Character Options) — intentionally unfilled."
    )

    def add_arguments(self, parser):
        parser.add_argument("--fixture", type=str, default=None,
                            help="Override the fixture path (default: spacemarches/fixtures/meshnet-pack-designs.json).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be created/updated without writing.")

    def handle(self, *args, **options):
        fixture = Path(settings.BASE_DIR) / "spacemarches" / (options["fixture"] or FIXTURE_RELATIVE)
        if not fixture.is_file():
            raise CommandError(f"Fixture not found: {fixture}")

        with open(fixture, encoding="utf-8") as fp:
            data = json.load(fp)

        dry = options["dry_run"]
        canonical = {} if dry else ensure_canonical_design_packs()

        created = updated = skipped = 0
        for row in data:
            pack_slug = (row.get("pack") or "").strip()
            if pack_slug == "ep-copt":
                skipped += 1  # ep-copt stays templated, never filled
                continue
            entry_id = (row.get("entry_id") or "").strip()
            if not entry_id:
                skipped += 1
                continue
            design_type = (row.get("design_type") or "").strip()
            category = DESIGN_TYPE_TO_CATEGORY.get(design_type)
            if category is None:
                skipped += 1
                continue

            is_st = pack_slug == "ep-crb-gm"
            system = row.get("system") if isinstance(row.get("system"), dict) else {}
            refs = row.get("references") if isinstance(row.get("references"), list) else []
            pages = sorted({str(p) for r in refs if isinstance(r, dict) for p in (r.get("pages") or [])})

            payload = {
                "source": "meshnet",
                "pack": pack_slug,
                "entry_id": entry_id,
                "name": (row.get("name") or entry_id)[:255],
                "entry_type": design_type,
                "category": category,
                "description": row.get("description") or "",
                "reference": ", ".join(pages),
                "is_storyteller_only": is_st,
                "is_custom": False,
                "design_pack": canonical.get(STORYTELLER_DESIGN_PACK if is_st else "ep-crb"),
                "system": system,
            }
            if dry:
                if not Ep2Entry.objects.filter(entry_id=entry_id).exists():
                    created += 1
                else:
                    updated += 1
                continue
            _, created_flag = Ep2Entry.objects.update_or_create(entry_id=entry_id, defaults=payload)
            if created_flag:
                created += 1
            else:
                updated += 1

        msg = f"{created} created, {updated} updated"
        if skipped:
            msg += f", {skipped} skipped (ep-copt + unknown types)"
        if dry:
            self.stdout.write(f"[dry-run] would {msg} (no rows written)")
            return
        self.stdout.write(self.style.SUCCESS(f"MeshNet seed complete: {msg}."))
