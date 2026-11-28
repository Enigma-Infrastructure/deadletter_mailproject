"""Idempotently load EP2e Life Path tables and entries from fixtures/ep2e_lifepath_tables.json.

Safe to re-run:
- Tables/entries are keyed by slug / (table, code).
- Rows marked ``is_custom=True`` by a Storyteller/Admin are preserved unless ``--overwrite-custom`` is passed.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from spacemarches.models import LifepathEntry, LifepathTable

FIXTURE_RELATIVE = "fixtures/ep2e_lifepath_tables.json"


class Command(BaseCommand):
    help = "Seed adjustable LifepathTable and LifepathEntry records from fixtures/ep2e_lifepath_tables.json."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fixture",
            type=str,
            default=None,
            help="Override the fixture path (default: spacemarches/fixtures/ep2e_lifepath_tables.json).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created/updated without writing to the database.",
        )
        parser.add_argument(
            "--overwrite-custom",
            action="store_true",
            help="Also overwrite rows flagged is_custom=True in Django Admin.",
        )

    def handle(self, *args, **options):
        fixture = Path(settings.BASE_DIR) / "spacemarches" / (options["fixture"] or FIXTURE_RELATIVE)
        if not fixture.is_file():
            raise CommandError(f"Fixture not found: {fixture}")

        with open(fixture, encoding="utf-8") as fp:
            tables_data = json.load(fp)

        dry = options["dry_run"]
        overwrite_custom = options["overwrite_custom"]

        t_created = t_updated = t_skipped = 0
        e_created = e_updated = e_skipped = 0

        for t_row in tables_data:
            slug = (t_row.get("slug") or "").strip()
            if not slug:
                continue

            existing_table = LifepathTable.objects.filter(slug=slug).first()
            if existing_table and existing_table.is_custom and not overwrite_custom:
                t_skipped += 1
                table_obj = existing_table
            else:
                table_payload = {
                    "step_number": int(t_row.get("step_number") or 0),
                    "code": (t_row.get("code") or "")[:32],
                    "name": (t_row.get("name") or slug)[:160],
                    "category": t_row.get("category") or LifepathTable.CAT_EVENT,
                    "die_type": t_row.get("die_type") or LifepathTable.DIE_D100,
                    "description": t_row.get("description") or "",
                    "allow_choice": bool(t_row.get("allow_choice", True)),
                    "rules_meta": t_row.get("rules_meta") or {},
                    "is_active": bool(t_row.get("is_active", True)),
                    "is_custom": False,
                    "sort_order": int(t_row.get("sort_order") or 0),
                }
                if dry:
                    if existing_table:
                        t_updated += 1
                    else:
                        t_created += 1
                    table_obj = existing_table
                else:
                    table_obj, created_flag = LifepathTable.objects.update_or_create(
                        slug=slug,
                        defaults=table_payload,
                    )
                    if created_flag:
                        t_created += 1
                    else:
                        t_updated += 1

            for e_row in t_row.get("entries") or []:
                code = (e_row.get("code") or "").strip()
                if not code:
                    continue
                existing_entry = (
                    LifepathEntry.objects.filter(table=table_obj, code=code).first()
                    if table_obj is not None
                    else None
                )
                if existing_entry and existing_entry.is_custom and not overwrite_custom:
                    e_skipped += 1
                    continue
                if dry:
                    if existing_entry:
                        e_updated += 1
                    else:
                        e_created += 1
                    continue

                entry_payload = {
                    "roll_min": e_row.get("roll_min"),
                    "roll_max": e_row.get("roll_max"),
                    "sub_roll_min": e_row.get("sub_roll_min"),
                    "sub_roll_max": e_row.get("sub_roll_max"),
                    "title": (e_row.get("title") or code)[:255],
                    "summary": e_row.get("summary") or "",
                    "next_table_slug": (e_row.get("next_table_slug") or "")[:80],
                    "effects": e_row.get("effects") or {},
                    "raw_source": e_row.get("raw_source") or {},
                    "is_active": bool(e_row.get("is_active", True)),
                    "is_custom": False,
                    "sort_order": int(e_row.get("sort_order") or 0),
                }
                _, e_created_flag = LifepathEntry.objects.update_or_create(
                    table=table_obj,
                    code=code,
                    defaults=entry_payload,
                )
                if e_created_flag:
                    e_created += 1
                else:
                    e_updated += 1

        prefix = "[dry-run] " if dry else ""
        msg = (
            f"{prefix}Lifepath seed: tables ({t_created} created, {t_updated} updated, {t_skipped} custom-skipped), "
            f"entries ({e_created} created, {e_updated} updated, {e_skipped} custom-skipped)."
        )
        if dry:
            self.stdout.write(msg)
        else:
            self.stdout.write(self.style.SUCCESS(msg))
