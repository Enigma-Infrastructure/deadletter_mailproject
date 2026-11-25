"""Tests for the seeded Eclipse Phase 2e reference data (Ep2Entry) and Compendium wiring."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

import json
from spacemarches.models import DesignPack, Ep2Entry
from spacemarches.services.design_pack_service import ensure_canonical_design_packs
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
        packs = ensure_canonical_design_packs()
        self.morph.design_pack = packs["ep-crb"]
        self.morph.save(update_fields=["design_pack"])
        self.gear.design_pack = packs["ep-crb"]
        self.gear.save(update_fields=["design_pack"])
        self.creature = make_entry(
            entry_id="view-char-0001",
            name="Clown Sprite",
            pack="creatures",
            category=Ep2Entry.CATEGORY_CHARACTER,
            entry_type="creature",
            design_pack=packs["ep-crb-storyteller"],
            is_storyteller_only=True,
        )

    def test_compendium_list_directory_and_filters(self):
        # Default unfiltered landing renders category/pack directory without dumping matching entries
        resp = self.client.get(reverse("spacemarches:compendium_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Browse by Category")
        self.assertContains(resp, "Rulebook &amp; Custom Design Packs")
        self.assertContains(resp, "Biomorphs")
        self.assertNotContains(resp, "matching entr")
        self.assertNotContains(resp, "Clown Sprite")

        # Default browse=all hides Storyteller-only entries
        browse_resp = self.client.get(reverse("spacemarches:compendium_list"), {"browse": "all"})
        self.assertEqual(browse_resp.status_code, 200)
        self.assertContains(browse_resp, "Ghost Biomorph")
        self.assertContains(browse_resp, "Chameleon Cloak")
        self.assertNotContains(browse_resp, "Clown Sprite")

        # storyteller=1 reveals Storyteller-only entries after player-first categories
        st_resp = self.client.get(reverse("spacemarches:compendium_list"), {"browse": "all", "storyteller": "1"})
        self.assertEqual(st_resp.status_code, 200)
        body = st_resp.content.decode("utf-8")
        self.assertLess(body.index("Ghost Biomorph"), body.index("Chameleon Cloak"))
        self.assertLess(body.index("Chameleon Cloak"), body.index("Clown Sprite"))

        morph_only = self.client.get(reverse("spacemarches:compendium_list"), {"category": "morph"})
        self.assertContains(morph_only, "Ghost Biomorph")
        self.assertNotContains(morph_only, "Chameleon Cloak")

        searched = self.client.get(reverse("spacemarches:compendium_list"), {"q": "Chameleon"})
        self.assertContains(searched, "Chameleon Cloak")
        self.assertNotContains(searched, "Ghost Biomorph")

    def test_api_orders_player_categories_before_characters_and_gates_storyteller(self):
        resp = self.client.get(reverse("spacemarches:api_ep2_data"))
        self.assertEqual(resp.status_code, 200)
        names = [row["name"] for row in resp.json()["results"]]
        self.assertEqual(names, ["Ghost Biomorph", "Chameleon Cloak"])

        st_resp = self.client.get(reverse("spacemarches:api_ep2_data"), {"storyteller": "1"})
        self.assertEqual(st_resp.status_code, 200)
        st_names = [row["name"] for row in st_resp.json()["results"]]
        self.assertEqual(st_names[:3], ["Ghost Biomorph", "Chameleon Cloak", "Clown Sprite"])

    def test_compendium_detail_sanitizes_html_and_shows_system_json(self):
        resp = self.client.get(reverse("spacemarches:compendium_detail", kwargs={"entry_id": "view-morph-0001"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ghost Biomorph")
        self.assertContains(resp, "<p>Stealth shell</p>")
        self.assertNotContains(resp, 'alert("xss")')
        self.assertContains(resp, "&quot;subtype&quot;: &quot;Biomorph&quot;")

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
        self.assertContains(meshnet_resp, "Quick browse by category:")
        self.assertContains(meshnet_resp, reverse("spacemarches:api_ep2_meta"))

        staff = User.objects.create_user(username="staff_ep2", password="pw", is_staff=True)
        self.client.force_login(staff)
        hub_resp = self.client.get(reverse("admin_hub"))
        self.assertEqual(hub_resp.status_code, 200)
        self.assertContains(hub_resp, "/spacemarches/compendium/")
        self.assertContains(hub_resp, "/admin/spacemarches/ep2entry/")



class DesignPackToolingTests(TestCase):
    def setUp(self):
        self.packs = ensure_canonical_design_packs()
        self.owner = User.objects.create_user(username="pack_owner", password="pw")
        self.other = User.objects.create_user(username="pack_other", password="pw")
        self.staff = User.objects.create_user(username="pack_staff", password="pw", is_staff=True)

    def test_canonical_packs_exist_and_seed_links_storyteller(self):
        self.assertEqual(
            set(self.packs.keys()),
            {"ep-crb", "ep-crb-storyteller", "ep-copt", "spacemarches"},
        )
        self.assertTrue(self.packs["ep-crb-storyteller"].is_storyteller_only)
        self.assertFalse(self.packs["ep-crb"].is_storyteller_only)
        call_command("seed_ep2_data", verbosity=0)
        self.assertTrue(
            Ep2Entry.objects.filter(pack="creatures", is_storyteller_only=True, design_pack__slug="ep-crb-storyteller").exists()
        )
        self.assertTrue(
            Ep2Entry.objects.filter(pack="biomorphs", is_storyteller_only=False, design_pack__slug="ep-crb").exists()
        )

    def test_custom_pack_create_entry_export_import_and_privacy(self):
        self.client.force_login(self.owner)
        create_resp = self.client.post(
            reverse("spacemarches:design_pack_list"),
            {
                "action": "create_pack",
                "name": "Gatecrasher Gear",
                "description": "Custom frontier hardware",
            },
        )
        self.assertEqual(create_resp.status_code, 302)
        pack = DesignPack.objects.get(name="Gatecrasher Gear")
        self.assertFalse(pack.is_official)
        self.assertEqual(pack.owner, self.owner)

        add_resp = self.client.post(
            reverse("spacemarches:design_pack_detail", kwargs={"slug": pack.slug}),
            {
                "action": "add_entry",
                "name": "Horizon Suit",
                "category": Ep2Entry.CATEGORY_GEAR,
                "pack": "armor",
                "entry_type": "armor",
                "reference": "House Rules p. 2",
                "description": "Dust-sealed vacsuit.",
                "system_json": json.dumps({"complexity": "moderate", "armorValues": {"energy": 4, "kinetic": 6}}),
            },
        )
        self.assertEqual(add_resp.status_code, 302)
        entry = Ep2Entry.objects.get(design_pack=pack, name="Horizon Suit")
        self.assertTrue(entry.is_custom)

        # Export portable JSON
        export_resp = self.client.get(reverse("spacemarches:design_pack_export", kwargs={"slug": pack.slug}))
        self.assertEqual(export_resp.status_code, 200)
        exported = json.loads(export_resp.content.decode("utf-8"))
        self.assertEqual(exported["schema"], "spacemarches-design-pack/v1")
        self.assertEqual(len(exported["entries"]), 1)

        # Private pack cannot be viewed or mutated by another user
        pack.is_public = False
        pack.save(update_fields=["is_public"])
        self.client.force_login(self.other)
        hidden_resp = self.client.get(reverse("spacemarches:design_pack_detail", kwargs={"slug": pack.slug}))
        self.assertEqual(hidden_resp.status_code, 404)

        # Non-staff cannot mutate official ep-crb pack
        forbid_resp = self.client.post(
            reverse("spacemarches:design_pack_detail", kwargs={"slug": "ep-crb"}),
            {"action": "add_entry", "name": "Illegal Edit", "category": Ep2Entry.CATEGORY_GEAR},
        )
        self.assertEqual(forbid_resp.status_code, 302)
        self.assertFalse(Ep2Entry.objects.filter(name="Illegal Edit").exists())

        # Re-import exported pack as another user creates their own copy cleanly
        import_resp = self.client.post(
            reverse("spacemarches:design_pack_list"),
            {
                "action": "import_pack",
                "pack_json": json.dumps(exported),
            },
        )
        self.assertEqual(import_resp.status_code, 302)
        self.assertEqual(DesignPack.objects.filter(name="Gatecrasher Gear").count(), 2)


class MeshNetAdapterServiceTests(TestCase):
    def setUp(self):
        self.packs = ensure_canonical_design_packs()
        self.owner = User.objects.create_user(username="mesh_owner", password="pw")
        self.other = User.objects.create_user(username="mesh_other", password="pw")

    def test_export_meshnet_pack_payload_converts_core_categories_and_skips_npc(self):
        from spacemarches.services.meshnet_adapter_service import export_meshnet_pack_payload

        crb = self.packs["ep-crb"]
        make_entry(
            entry_id="mn-morph-1",
            design_pack=crb,
            pack="biomorphs",
            category=Ep2Entry.CATEGORY_MORPH,
            entry_type="biological",
            name="Exalt",
            system={
                "subtype": "Biomorph",
                "acquisition": {"cost": 3, "availability": 70},
                "pools": {"insight": 2, "moxie": 1, "vigor": 1, "flex": 1},
                "movementRates": [{"type": "walker", "base": 4, "full": 20}],
            },
        )
        make_entry(
            entry_id="mn-armor-1",
            design_pack=crb,
            pack="armor",
            category=Ep2Entry.CATEGORY_GEAR,
            entry_type="armor",
            name="Vacsuit Light",
            system={"complexity": "moderate", "armorValues": {"energy": 5, "kinetic": 5}},
        )
        make_entry(
            entry_id="mn-gun-1",
            design_pack=crb,
            pack="kinetic-weapons",
            category=Ep2Entry.CATEGORY_GEAR,
            entry_type="firearm",
            name="Light Pistol",
            system={
                "complexity": "minor",
                "range": 10,
                "ammo": 14,
                "attack": {"damageFormula": "2d6", "armorUsed": "kinetic", "modes": ["ss", "sa"]},
            },
        )
        make_entry(
            entry_id="mn-npc-skip",
            design_pack=crb,
            pack="creatures",
            category=Ep2Entry.CATEGORY_CHARACTER,
            entry_type="character",
            name="Skip Raw NPC",
            system={},
        )

        payload = export_meshnet_pack_payload(crb)
        self.assertEqual(payload["id"], "ep-crb")
        designs = payload["pack"]["designs"]
        self.assertIn("biologicalBody", designs)
        self.assertIn("armorMod", designs)
        self.assertIn("firearm", designs)
        self.assertNotIn("character", designs)

    def test_api_meshnet_packs_gates_storyteller_and_private_packs(self):
        st_pack = self.packs["ep-crb-storyteller"]
        make_entry(
            entry_id="mn-eps-1",
            design_pack=st_pack,
            pack="psi-epsilon",
            category=Ep2Entry.CATEGORY_SLEIGHT,
            entry_type="epsilon",
            name="Exsurgent Pulse",
            is_storyteller_only=True,
            system={"infectionMod": 2, "duration": "instant", "action": "complex"},
        )
        priv = DesignPack.objects.create(
            slug="private-house",
            name="Private House",
            owner=self.owner,
            is_public=False,
        )
        make_entry(
            entry_id="mn-priv-1",
            design_pack=priv,
            pack="hardware",
            category=Ep2Entry.CATEGORY_GEAR,
            entry_type="tech",
            name="Secret Tool",
            system={"complexity": "minor"},
        )

        # Anonymous user without storyteller=1 omits ep-crb-storyteller and private packs
        anon_resp = self.client.get(reverse("spacemarches:api_meshnet_packs"), {"storyteller": "0"})
        self.assertEqual(anon_resp.status_code, 200)
        anon_ids = {p["id"] for p in anon_resp.json()["packs"]}
        self.assertIn("ep-crb", anon_ids)
        self.assertNotIn("ep-crb-storyteller", anon_ids)
        self.assertNotIn("private-house", anon_ids)

        # Default or storyteller=1 reveals ep-crb-storyteller
        st_resp = self.client.get(reverse("spacemarches:api_meshnet_packs"), {"storyteller": "1"})
        st_ids = {p["id"] for p in st_resp.json()["packs"]}
        self.assertIn("ep-crb-storyteller", st_ids)
        self.assertNotIn("private-house", st_ids)

        # Owner sees their own private custom pack
        self.client.force_login(self.owner)
        owner_resp = self.client.get(reverse("spacemarches:api_meshnet_packs"))
        owner_ids = {p["id"] for p in owner_resp.json()["packs"]}
        self.assertIn("private-house", owner_ids)

    def test_generator_boot_payload_exposes_compendium_and_pack_urls(self):
        resp = self.client.get(reverse("spacemarches:meshnet"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("spacemarches:api_meshnet_packs"))
        self.assertContains(resp, reverse("spacemarches:design_pack_list"))
