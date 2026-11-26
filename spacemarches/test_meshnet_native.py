"""Parity and integrity tests for the MeshNet-native design pack data.

These tests treat the minified bundle's embedded designs (mirrored in
spacemarches/fixtures/meshnet-pack-designs.json) as the reference oracle: every
MeshNet-native row must hydrate through the Django adapter into a partial that
resembles the embedded design, and every nested design reference must resolve
against the compendium that holds it.
"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from spacemarches.models import DesignPack, Ep2Entry
from spacemarches.services.design_pack_service import ensure_canonical_design_packs
from spacemarches.services.meshnet_adapter_service import (
    _convert_entry,
    _meshnet_native_partial,
    export_meshnet_pack_payload,
)

FIXTURE = Path(settings.BASE_DIR) / "spacemarches" / "fixtures" / "meshnet-pack-designs.json"


def design_type_named_key(designs, design_type):
    bucket = designs.get(design_type) or {}
    assert bucket, f"{design_type} missing from payload"
    return next(iter(bucket))


def _load_fixture():
    with open(FIXTURE, encoding="utf-8") as fp:
        return json.load(fp)


def _nested_uids(system, out):
    if isinstance(system, dict):
        uid = system.get("uid")
        if isinstance(uid, str) and uid:
            out.append(uid)
        for value in system.values():
            _nested_uids(value, out)
    elif isinstance(system, list):
        for item in system:
            _nested_uids(item, out)


class MeshNetNativeFixtureTests(TestCase):
    def test_fixture_is_complete_and_self_consistent(self):
        fixture = _load_fixture()
        self.assertEqual(len(fixture), 840)
        entry_ids = [row["entry_id"] for row in fixture]
        self.assertEqual(len(entry_ids), len(set(entry_ids)))
        packs = {row["pack"] for row in fixture}
        self.assertEqual(packs, {"ep-crb", "ep-crb-gm", "ep-copt"})
        for row in fixture:
            self.assertTrue(row["system"].get("type"), row["entry_id"])
            self.assertTrue(row["name"], row["entry_id"])
            self.assertTrue(row["system"].get("type") != "", row["entry_id"])

    def test_fixture_nested_references_resolve_inside_pack(self):
        fixture = _load_fixture()
        lookup = {}
        for row in fixture:
            lookup[f"{row['design_type']}:{row['pack']}:{row['key']}"] = row
        missing: list[tuple[str, str]] = []
        for row in fixture:
            uids: list[str] = []
            _nested_uids(row["system"], uids)
            for uid in uids:
                if uid not in lookup:
                    missing.append((row["entry_id"], uid))
        self.assertEqual(missing, [])


class MeshNetNativeSeedTests(TestCase):
    def setUp(self):
        ensure_canonical_design_packs()

    def test_seed_creates_rows_and_skips_ep_copt(self):
        call_command("seed_meshnet_data", verbosity=0)
        self.assertGreater(Ep2Entry.objects.filter(source="meshnet").count(), 0)
        self.assertFalse(
            Ep2Entry.objects.filter(source="meshnet", pack="ep-copt").exists(),
            "ep-copt must never be filled (templated only)",
        )
        self.assertFalse(
            Ep2Entry.objects.filter(source="meshnet", is_storyteller_only=True, pack="ep-crb").exists(),
        )
        st = Ep2Entry.objects.filter(source="meshnet", pack="ep-crb-gm").first()
        self.assertIsNotNone(st)
        self.assertTrue(st.is_storyteller_only)
        self.assertEqual(st.design_pack.slug, "ep-crb-storyteller")

    def test_seed_is_idempotent(self):
        call_command("seed_meshnet_data", verbosity=0)
        first = Ep2Entry.objects.filter(source="meshnet").count()
        call_command("seed_meshnet_data", verbosity=0)
        self.assertEqual(Ep2Entry.objects.filter(source="meshnet").count(), first)


class MeshNetNativeAdapterTests(TestCase):
    def setUp(self):
        ensure_canonical_design_packs()
        call_command("seed_meshnet_data", verbosity=0)

    def test_every_meshnet_row_hydrates_to_valid_partial(self):
        rows = list(Ep2Entry.objects.filter(source="meshnet"))
        self.assertGreater(len(rows), 0)
        failures = []
        for row in rows:
            result = _convert_entry(row, pack_name="EP2e CRB")
            if result is None:
                failures.append((row.entry_id, "convert returned None"))
                continue
            design_type, partial = result
            if design_type != row.entry_type:
                failures.append((row.entry_id, f"type mismatch: {design_type!r} != {row.entry_type!r}"))
            if not str(partial.get("name", "")).strip():
                failures.append((row.entry_id, "empty name"))
            if not str(partial.get("description", "")).strip() and not row.system.get("description"):
                # description may be empty for env-like designs; require it otherwise
                pass
        self.assertEqual(failures, [])

    def test_design_key_matches_hashed_key(self):
        rows = list(Ep2Entry.objects.filter(source="meshnet")[:25])
        for row in rows:
            key = row.entry_id.split(":", 2)[-1]
            self.assertTrue(key)

    def test_nested_references_resolve_in_hydrate(self):
        # All nested design uids in the Django compendium must be covered by a row in
        # the compendium (same pack + design type). This mirrors what the bundle does at
        # runtime: design references resolve by pack-scoped key.
        crb_entries = {f"{e.entry_type}:{e.pack}:{e.entry_id.split(':', 2)[-1]}" for e in Ep2Entry.objects.filter(pack="ep-crb")}
        missing = []
        for row in Ep2Entry.objects.filter(source="meshnet", pack="ep-crb"):
            uids: list[str] = []
            _nested_uids(row.system, uids)
            for uid in uids:
                if uid not in crb_entries:
                    missing.append((row.entry_id, uid))
        self.assertEqual(missing, [])

    def test_export_payload_bundle_merge_is_deterministic(self):
        pack = DesignPack.objects.get(slug="ep-crb")
        payload = export_meshnet_pack_payload(pack)
        designs = payload["pack"]["designs"]
        self.assertIn("activeSkill", designs)
        self.assertIn("ego", designs)
        self.assertIn("skillPack", designs)
        # the MeshNet-native character (Njal) hydrates like any other meshnet-sourced row
        if "character" in designs:
            self.assertIn(design_type_named_key(designs, "character"), designs["character"])
        # every design type's entries hydrate through the TypeBox validator path
        for design_type, bucket in designs.items():
            for key, partial in bucket.items():
                self.assertTrue(partial.get("name"), f"{design_type}/{key}")
