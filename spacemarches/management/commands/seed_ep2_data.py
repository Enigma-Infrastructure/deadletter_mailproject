"""Idempotently load the Eclipse Phase 2e reference-data fixture into Ep2Entry.

The fixture (spacemarches/fixtures/ep2_entries.json) is generated from the
Bubz43/ep2e Foundry packs (CC BY 4.0) and preserves the full pack `system`
payload per entry. Safe to re-run: existing rows are updated in place keyed
by entry_id, new rows are created, missing rows are left alone (no deletes).
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from spacemarches.models import Ep2Entry
from spacemarches.services.design_pack_service import (
    ensure_canonical_design_packs,
    is_storyteller_entry_payload,
)

FIXTURE_RELATIVE = "fixtures/ep2_entries.json"


class Command(BaseCommand):
    help = "Seed the Ep2Entry table from fixtures/ep2_entries.json (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixture",
            type=str,
            default=None,
            help="Override the fixture path (default: spacemarches/fixtures/ep2_entries.json).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created/updated without writing to the database.",
        )

    def handle(self, *args, **options):
        fixture = Path(settings.BASE_DIR) / "spacemarches" / (options["fixture"] or FIXTURE_RELATIVE)
        if not fixture.is_file():
            raise CommandError(f"Fixture not found: {fixture}")

        with open(fixture, encoding="utf-8") as fp:
            data = json.load(fp)

        ids_in_fixture = set()
        created = updated = 0
        dry = options["dry_run"]
        canonical_packs = {} if dry else ensure_canonical_design_packs()

        for row in data:
            fields = row.get("fields", row)
            entry_id = (fields.get("entry_id") or "").strip()
            if not entry_id:
                continue
            pack_slug = fields.get("pack") or ""
            sys_payload = fields.get("system") or {}
            is_st = is_storyteller_entry_payload(pack_slug, sys_payload)
            payload = {
                "source": fields.get("source") or "bubz-ep2e",
                "pack": pack_slug,
                "entry_id": entry_id,
                "name": (fields.get("name") or entry_id)[:255],
                "entry_type": fields.get("entry_type") or "",
                "category": fields.get("category") or "misc",
                "description": fields.get("description") or "",
                "reference": fields.get("reference") or "",
                "is_storyteller_only": is_st,
                "is_custom": False,
                "system": sys_payload,
            }
            if not dry:
                payload["design_pack"] = (
                    canonical_packs["ep-crb-storyteller"] if is_st else canonical_packs["ep-crb"]
                )

            exists = Ep2Entry.objects.filter(entry_id=entry_id).exists()
            if dry:
                if exists:
                    updated += 1
                else:
                    created += 1
                ids_in_fixture.add(entry_id)
                continue

            _, created_flag = Ep2Entry.objects.update_or_create(
                entry_id=entry_id,
                defaults=payload,
            )
            if created_flag:
                created += 1
            else:
                updated += 1
            ids_in_fixture.add(entry_id)

        if dry:
            self.stdout.write(
                f"[dry-run] would create {created}, update {updated} "
                f"({len(ids_in_fixture)} rows in fixture; existing rows untouched)"
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Ep2Entry seed complete: {created} created, {updated} updated, "
                f"{len(ids_in_fixture)} total in fixture."
            )
        )
