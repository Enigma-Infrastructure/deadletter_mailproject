"""Tests for the seeded Eclipse Phase 2e reference data (Ep2Entry)."""
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from spacemarches.models import Ep2Entry


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


class Ep2EntryApiTests(TestCase):
    def setUp(self):
        self.gear_entry = make_entry(entry_id="api-gear-0001", name="Kinetic Coat", pack="armor")
        self.morph_entry = make_entry(
            entry_id="api-morph-0001",
            name="Kinetic Bouncer",
            pack="biomorphs",
            category=Ep2Entry.CATEGORY_MORPH,
            entry_type="biological",
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

    def test_single_entry_missing_returns_404(self):
        response = self.client.get(reverse("spacemarches:api_ep2_entry", kwargs={"entry_id": "does-not-exist"}))
        self.assertEqual(response.status_code, 404)

    def test_limit_capped_at_500(self):
        response = self.client.get(reverse("spacemarches:api_ep2_data"), {"limit": 100000})
        payload = response.json()
        self.assertEqual(payload["limit"], 500)

    def test_system_payload_preserved(self):
        response = self.client.get(reverse("spacemarches:api_ep2_entry", kwargs={"entry_id": "api-gear-0001"}))
        payload = response.json()
        self.assertEqual(payload["system"]["reference"], "Eclipse Phase Second Edition p. 999")
        self.assertIn("source_url", payload)
