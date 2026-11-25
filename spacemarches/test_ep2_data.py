"""Tests for the seeded Eclipse Phase 2e reference data (Ep2Entry) and Compendium wiring."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from spacemarches.models import Ep2Entry
from spacemarches.services.ep2_service import (
    extract_ep2_highlights,
    format_pack_label,
    get_ep2_source_url,
    sanitize_ep2_html,
    strip_ep2_text,
)

User = get_user_model()


def make_entry(**overrides):
    defaults = {
        "entry_id": "test-entry-0001",
        "pack": "armor",
        "name": "Test Armor",
        "entry_type": "armor",
        "category": Ep2Entry.CATEGORY_GEAR,
        "description": "Resilient test fibers.",
        "reference": "Eclipse Phase Second Edition p. 999",
        "system": {"description": "Resilient test fibers.", "reference": "Eclipse Phase Second Edition p. 999"},
    }
    defaults.update(overrides)
    return Ep2Entry.objects.create(**defaults)


class Ep2EntryModelTests(TestCase):
    def test_str_and_ordering(self):
        entry = make_entry()
        self.assertIn("Test Armor", str(entry))
        self.assertIn("armor", str(entry))

    def test_entry_id_is_unique(self):
        make_entry()
        with self.assertRaises(Exception):
            make_entry()  # same entry_id

    def test_fields_round_trip(self):
        entry = make_entry(category=Ep2Entry.CATEGORY_MORPH, pack="biomorphs")
        entry.refresh_from_db()
        self.assertEqual(entry.category, "morph")
        self.assertEqual(entry.pack, "biomorphs")
        self.assertEqual(entry.source, "bubz-ep2e")


class Ep2EntrySeedTests(TestCase):
    def test_seed_command_is_idempotent(self):
        entry = make_entry()
        call_command("seed_ep2_data", verbosity=0)
        count_after_first = Ep2Entry.objects.count()
        self.assertGreaterEqual(count_after_first, 1)
        self.assertTrue(Ep2Entry.objects.filter(entry_id=entry.entry_id).exists())
        # Second run must not create duplicates
        call_command("seed_ep2_data", verbosity=0)
        self.assertEqual(Ep2Entry.objects.count(), count_after_first)
        # Fixture-seeded rows land in the table
        self.assertTrue(Ep2Entry.objects.filter(pack="armor").exists())

    def test_seed_dry_run_does_not_write(self):
        before = Ep2Entry.objects.count()
        call_command("seed_ep2_data", "--dry-run", verbosity=0)
        self.assertEqual(Ep2Entry.objects.count(), before)

    def test_seed_missing_fixture_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("seed_ep2_data", "--fixture", "fixtures/does_not_exist.json", verbosity=0)


class Ep2ServiceTests(TestCase):
    def test_sanitize_ep2_html_strips_scripts_and_attributes(self):
        dirty = '<p onclick="alert(1)">Safe text</p><script>evil()</script><strong>Bold</strong>'
        cleaned = sanitize_ep2_html(dirty)
        self.assertIn("<p>Safe text</p>", cleaned)
        self.assertIn("<strong>Bold</strong>", cleaned)
        self.assertNotIn("<script>", cleaned)
        self.assertNotIn("onclick", cleaned)
        self.assertEqual(strip_ep2_text(dirty), "Safe text Bold")

    def test_format_pack_label_and_source_url(self):
        self.assertEqual(format_pack_label("qe-comms-gear"), "QE Comms Gear")
        self.assertEqual(format_pack_label("combat-augmentations"), "Combat Augmentations")
        self.assertIn("Bubz43/ep2e", get_ep2_source_url("bubz-ep2e"))
        self.assertIn("mesh-net", get_ep2_source_url("mesh-net"))
        self.assertEqual(get_ep2_source_url("unknown-source"), "")

    def test_extract_highlights_for_morph_and_armor(self):
        morph = make_entry(
            entry_id="hl-morph",
            pack="biomorphs",
            category=Ep2Entry.CATEGORY_MORPH,
            entry_type="biological",
            name="Bouncer",
            system={
                "subtype": "Biomorph",
                "acquisition": {"cost": 4, "availability": 60, "complexity": "minor", "restricted": False},
                "pools": {"insight": 1, "moxie": 0, "vigor": 1, "flex": 2},
                "movementRates": [{"type": "walker", "base": 4, "full": 12}],
            },
        )
        morph_hl = {h["label"]: h["value"] for h in extract_ep2_highlights(morph)}
        self.assertEqual(morph_hl["MP Cost"], "4")
        self.assertIn("INS 1", morph_hl["Pools"])
        self.assertIn("Walker 4/12", morph_hl["Movement"])

        armor = make_entry(
            entry_id="hl-armor",
            pack="armor",
            category=Ep2Entry.CATEGORY_GEAR,
            entry_type="armor",
            name="Armor Clothing",
            system={
                "complexity": "minor",
                "armorValues": {"energy": 1, "kinetic": 3},
            },
        )
        armor_hl = {h["label"]: h["value"] for h in extract_ep2_highlights(armor)}
        self.assertEqual(armor_hl["Armor (E/K)"], "1 / 3")
        self.assertEqual(armor_hl["Complexity"], "Minor")


class Ep2EntryApiTests(TestCase):
    def setUp(self):
        self.gear_entry = make_entry(
            entry_id="api-gear-0001",
            name="Kinetic Coat",
            pack="armor",
            system={
                "description": "Resilient test fibers.",
                "reference": "Eclipse Phase Second Edition p. 999",
                "complexity": "minor",
                "armorValues": {"energy": 1, "kinetic": 3},
            },
        )
        self.morph_entry = make_entry(
            entry_id="api-morph-0001",
            name="Kinetic Bouncer",
            pack="biomorphs",
            category=Ep2Entry.CATEGORY_MORPH,
            entry_type="biological",
            source="mesh-net",
        )

    def test_list_returns_entries_and_total_count(self):
        response = self.client.get(reverse("spacemarches:api_ep2_data"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], Ep2Entry.objects.count())
        names = [r["name"] for r in payload["results"]]
        self.assertIn("Kinetic Coat", names)

    def test_filter_by_category(self):
        response = self.client.get(reverse("spacemarches:api_ep2_data"), {"category": "morph"})
        payload = response.json()
        self.assertTrue(all(r["category"] == "morph" for r in payload["results"]))
        self.assertTrue(any(r["name"] == "Kinetic Bouncer" for r in payload["results"]))

    def test_search_by_name_and_limit_cap(self):
        response = self.client.get(reverse("spacemarches:api_ep2_data"), {"q": "Kinetic", "limit": 1})
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertGreaterEqual(payload["count"], 2)

    def test_single_entry_by_id(self):
        response = self.client.get(reverse("spacemarches:api_ep2_entry", kwargs={"entry_id": "api-gear-0001"}))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["name"], "Kinetic Coat")
        self.assertEqual(payload["pack"], "armor")
        self.assertEqual(payload["compendium_url"], reverse("spacemarches:compendium_detail", kwargs={"entry_id": "api-gear-0001"}))
        self.assertTrue(any(h["label"] == "Armor (E/K)" for h in payload["highlights"]))

    def test_single_entry_missing_returns_404(self):
        response = self.client.get(reverse("spacemarches:api_ep2_entry", kwargs={"entry_id": "does-not-exist"}))
        self.assertEqual(response.status_code, 404)

    def test_limit_capped_at_500(self):
        response = self.client.get(reverse("spacemarches:api_ep2_data"), {"limit": 100000})
        payload = response.json()
        self.assertEqual(payload["limit"], 500)

    def test_system_payload_preserved_and_source_url_follows_source(self):
        response = self.client.get(reverse("spacemarches:api_ep2_entry", kwargs={"entry_id": "api-gear-0001"}))
        payload = response.json()
        self.assertEqual(payload["system"]["reference"], "Eclipse Phase Second Edition p. 999")
        self.assertIn("Bubz43/ep2e", payload["source_url"])

        morph_resp = self.client.get(reverse("spacemarches:api_ep2_entry", kwargs={"entry_id": "api-morph-0001"}))
        self.assertIn("mesh-net", morph_resp.json()["source_url"])

    def test_meta_endpoint_returns_categories_and_packs(self):
        resp = self.client.get(reverse("spacemarches:api_ep2_meta"))
        self.assertEqual(resp.status_code, 200)
        meta = resp.json()
        self.assertEqual(meta["total_entries"], 2)
        self.assertEqual(meta["pack_count"], 2)
        cat_values = {c["value"] for c in meta["categories"]}
        self.assertEqual(cat_values, {"gear", "morph"})

        filtered = self.client.get(reverse("spacemarches:api_ep2_meta"), {"category": "morph"}).json()
        self.assertEqual([p["pack"] for p in filtered["packs"]], ["biomorphs"])


class Ep2CompendiumViewsTests(TestCase):
    def setUp(self):
        self.morph = make_entry(
            entry_id="view-morph-0001",
            name="Ghost Biomorph",
            pack="biomorphs",
            category=Ep2Entry.CATEGORY_MORPH,
            entry_type="biological",
            description='<p>Stealth shell</p><script>alert("xss")</script>',
            system={"subtype": "Biomorph", "acquisition": {"cost": 3}},
        )
        self.gear = make_entry(
            entry_id="view-gear-0001",
            name="Chameleon Cloak",
            pack="armor",
            category=Ep2Entry.CATEGORY_GEAR,
            entry_type="armor",
        )

    def test_compendium_list_and_filters(self):
        resp = self.client.get(reverse("spacemarches:compendium_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ghost Biomorph")
        self.assertContains(resp, "Chameleon Cloak")

        morph_only = self.client.get(reverse("spacemarches:compendium_list"), {"category": "morph"})
        self.assertContains(morph_only, "Ghost Biomorph")
        self.assertNotContains(morph_only, "Chameleon Cloak")

        searched = self.client.get(reverse("spacemarches:compendium_list"), {"q": "Chameleon"})
        self.assertContains(searched, "Chameleon Cloak")
        self.assertNotContains(searched, "Ghost Biomorph")

    def test_compendium_detail_sanitizes_html_and_shows_system_json(self):
        resp = self.client.get(reverse("spacemarches:compendium_detail", kwargs={"entry_id": "view-morph-0001"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ghost Biomorph")
        self.assertContains(resp, "<p>Stealth shell</p>")
        self.assertNotContains(resp, "<script>")
        self.assertContains(resp, '"subtype": "Biomorph"')

        missing = self.client.get(reverse("spacemarches:compendium_detail", kwargs={"entry_id": "nope"}))
        self.assertEqual(missing.status_code, 404)

    def test_portal_and_meshnet_drawer_and_admin_hub_wiring(self):
        portal_resp = self.client.get(reverse("spacemarches:portal"))
        self.assertEqual(portal_resp.status_code, 200)
        self.assertContains(portal_resp, "EP2E Compendium")
        self.assertContains(portal_resp, reverse("spacemarches:compendium_list"))

        meshnet_resp = self.client.get(reverse("spacemarches:meshnet"))
        self.assertEqual(meshnet_resp.status_code, 200)
        self.assertContains(meshnet_resp, "sm-compendium-drawer")
        self.assertContains(meshnet_resp, "EP2E Lookup")
        self.assertContains(meshnet_resp, reverse("spacemarches:api_ep2_meta"))

        staff = User.objects.create_user(username="staff_ep2", password="pw", is_staff=True)
        self.client.force_login(staff)
        hub_resp = self.client.get(reverse("admin_hub"))
        self.assertEqual(hub_resp.status_code, 200)
        self.assertContains(hub_resp, "/spacemarches/compendium/")
        self.assertContains(hub_resp, "/admin/spacemarches/ep2entry/")
