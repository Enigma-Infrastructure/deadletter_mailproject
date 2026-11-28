import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from spacemarches.models import ArchiveEntry, CharacterDossier, ForumThread, GeneratedCharacter
from spacemarches.services.character_sync_service import (
    export_generated_character_html,
    export_generated_character_markdown,
    extract_point_buy_summary,
)

User = get_user_model()


def make_sample_point_buy_payload(*, name: str = "Kestrel", concept: str = "Gatecrasher"):
    return {
        "type": "point-buy-exported",
        "createdAt": "2026-11-24T12:00:00Z",
        "packs": {
            "crb": {
                "traits": {
                    "tr1": {"name": {"en-US": "Stubborn"}},
                },
                "sleights": {
                    "sl1": {"name": {"en-US": "Omniscient"}},
                },
            }
        },
        "pointBuy": {
            "name": {"en-US": name},
            "fullName": {"en-US": f"{name} Solis"},
            "concept": {"en-US": concept},
            "egoType": {"en-US": "Ruster"},
            "flexPoints": 2,
            "aptitudes": {
                "cog": 15,
                "int": 20,
                "ref": 15,
                "sav": 10,
                "som": 15,
                "wil": 15,
            },
            "skillPacks": {
                "background": {"name": {"en-US": "Colonist"}},
                "career": {"name": {"en-US": "Scout"}},
            },
            "morphs": {
                "m1": {"customName": {"en-US": "Splicer"}},
            },
            "egoTraits": {
                "t1": {"design": {"id": "tr1"}},
            },
            "sleights": {
                "s1": {"design": {"id": "sl1"}},
            },
            "reputations": {
                "r1": {"name": {"en-US": "@-rep"}, "score": 55},
            },
            "languages": [{"en-US": "English"}, {"en-US": "Mandarin"}],
            "motivations": {
                "mot1": {"cause": {"en-US": "Exoplanet Survival"}, "stance": "support"},
            },
            "skills": {
                "sk1": {"name": {"en-US": "Hardware"}, "points": 35},
                "sk2": {"name": {"en-US": "Survival"}, "points": 45},
            },
        },
    }


class GeneratedCharacterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="agent1")
        self.other = User.objects.create_user(username="agent2")
        self.dossier = CharacterDossier.objects.create(
            user=self.user,
            character_name="Kestrel Dossier",
            slug="kestrel-dossier",
        )
        self.other_dossier = CharacterDossier.objects.create(
            user=self.other,
            character_name="Other Dossier",
            slug="other-dossier",
        )
        self.archive = ArchiveEntry.objects.create(
            slug="sector-brief",
            title="Sector Brief",
            classification_level="PUBLIC",
            body="Briefing.",
            is_public=True,
            author=self.user,
        )
        self.thread = ForumThread.objects.create(
            title="Brief Notes",
            slug="brief-notes",
            author=self.user,
            related_archive=self.archive,
            is_public=True,
            body="Notes.",
        )

    def test_extract_summary_and_external_id_constraint(self):
        payload = make_sample_point_buy_payload(name="Echo")
        summary = extract_point_buy_summary(payload)
        self.assertEqual(summary["character_name"], "Echo")
        self.assertEqual(summary["full_name"], "Echo Solis")
        self.assertEqual(summary["concept"], "Gatecrasher")
        self.assertEqual(summary["aptitudes"]["int"], 20)
        self.assertEqual(summary["morphs"], ["Splicer"])
        self.assertEqual(summary["traits"], ["Stubborn"])
        self.assertEqual(summary["sleights"], ["Omniscient"])
        self.assertEqual(summary["skill_count"], 2)

        # Multiple blank external_ids are allowed on the same user
        c1 = GeneratedCharacter.objects.create(user=self.user, character_name="A", raw_data=payload)
        c2 = GeneratedCharacter.objects.create(user=self.user, character_name="B", raw_data=payload)
        self.assertNotEqual(c1.pk, c2.pk)

        # Duplicate non-empty external_id on same user raises IntegrityError
        GeneratedCharacter.objects.create(
            user=self.user,
            external_id="dexie-1",
            character_name="Echo",
            raw_data=payload,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                GeneratedCharacter.objects.create(
                    user=self.user,
                    external_id="dexie-1",
                    character_name="Echo Dup",
                    raw_data=payload,
                )

        # Same external_id on different user is allowed
        GeneratedCharacter.objects.create(
            user=self.other,
            external_id="dexie-1",
            character_name="Echo Other",
            raw_data=payload,
        )

    def test_public_generator_and_m3_palette_across_pages(self):
        for url_name in ("spacemarches:meshnet", "spacemarches:generator"):
            gen_resp = self.client.get(reverse(url_name))
            self.assertEqual(gen_resp.status_code, 200)
            self.assertContains(gen_resp, "spacemarches-generator-boot")
            self.assertContains(gen_resp, '"authenticated": false')
            self.assertContains(gen_resp, "Log in to Save")
            self.assertContains(gen_resp, "sm-palette-panel")
            self.assertContains(gen_resp, "spacemarches-palette.js")
            self.assertContains(gen_resp, 'Mesh<span class="sm-brand-sector-accent">Net</span>')
            self.assertContains(gen_resp, f'href="{reverse("spacemarches:portal")}" rel="external"')
            self.assertContains(gen_resp, f'href="{reverse("spacemarches:archive_list")}" rel="external"')
            self.assertContains(gen_resp, f'href="{reverse("spacemarches:forum_list")}" rel="external"')

        for name, kwargs in [
            ("spacemarches:portal", {}),
            ("spacemarches:archive_list", {}),
            ("spacemarches:archive_detail", {"slug": self.archive.slug}),
            ("spacemarches:forum_list", {}),
            ("spacemarches:forum_detail", {"slug": self.thread.slug}),
        ]:
            resp = self.client.get(reverse(name, kwargs=kwargs))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, reverse("spacemarches:meshnet"))
            self.assertContains(resp, ">MeshNet<")
            self.assertNotContains(resp, "Terminal Shell")
            self.assertContains(resp, "sm-palette-panel")
            self.assertContains(resp, 'data-sm-set-contrast="1"')
            self.assertContains(resp, 'Mesh<span class="sm-brand-sector-accent">Net</span>')
            self.assertContains(resp, f'href="{reverse("spacemarches:meshnet")}" rel="external"')

    def test_anonymous_blocked_from_cloud_roster_and_apis(self):
        protected = [
            ("GET", reverse("spacemarches:character_roster")),
            ("POST", reverse("spacemarches:character_roster")),
            ("GET", reverse("spacemarches:api_characters")),
            ("POST", reverse("spacemarches:api_characters")),
        ]
        for method, url in protected:
            resp = self.client.get(url) if method == "GET" else self.client.post(url, {})
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/accounts/login/", resp["Location"])

    def test_authenticated_api_crud_batch_link_and_isolation(self):
        self.client.force_login(self.user)
        payload = make_sample_point_buy_payload(name="Vesper")

        # Save character via API
        create_resp = self.client.post(
            reverse("spacemarches:api_characters"),
            data=json.dumps(
                {
                    "external_id": "pb-abc",
                    "raw_data": payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_resp.status_code, 200)
        data = create_resp.json()
        self.assertTrue(data["created"])
        char_id = data["character"]["id"]
        self.assertEqual(data["character"]["character_name"], "Vesper")

        # Upsert with same external_id updates in place
        updated_payload = make_sample_point_buy_payload(name="Vesper Mk2")
        upd_resp = self.client.post(
            reverse("spacemarches:api_characters"),
            data=json.dumps(
                {
                    "external_id": "pb-abc",
                    "raw_data": updated_payload,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(upd_resp.status_code, 200)
        self.assertFalse(upd_resp.json()["created"])
        self.assertEqual(upd_resp.json()["character"]["id"], char_id)
        self.assertEqual(upd_resp.json()["character"]["character_name"], "Vesper Mk2")

        # Link to existing dossier
        link_resp = self.client.post(
            reverse("spacemarches:api_character_link_dossier", kwargs={"pk": char_id}),
            data=json.dumps({"dossier_id": self.dossier.pk}),
            content_type="application/json",
        )
        self.assertEqual(link_resp.status_code, 200)
        self.assertEqual(link_resp.json()["character"]["dossier_id"], self.dossier.pk)

        # Dossier detail displays linked character summary
        dossier_resp = self.client.get(
            reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug})
        )
        self.assertEqual(dossier_resp.status_code, 200)
        self.assertContains(dossier_resp, "Linked Point-Buy Character Sheets (1)")
        self.assertContains(dossier_resp, "Vesper Mk2")

        # Reject linking another user's dossier
        bad_link = self.client.post(
            reverse("spacemarches:api_character_link_dossier", kwargs={"pk": char_id}),
            data=json.dumps({"dossier_id": self.other_dossier.pk}),
            content_type="application/json",
        )
        self.assertEqual(bad_link.status_code, 400)

        # Batch import & create new dossier for second character
        batch_resp = self.client.post(
            reverse("spacemarches:api_characters"),
            data=json.dumps(
                {
                    "characters": [
                        {
                            "external_id": "pb-batch-2",
                            "raw_data": make_sample_point_buy_payload(name="Nyssa"),
                        }
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(batch_resp.status_code, 200)
        nyssa_id = batch_resp.json()["characters"][0]["id"]
        new_dossier_link = self.client.post(
            reverse("spacemarches:api_character_link_dossier", kwargs={"pk": nyssa_id}),
            data=json.dumps({"create_dossier": True}),
            content_type="application/json",
        )
        self.assertEqual(new_dossier_link.status_code, 200)
        self.assertEqual(new_dossier_link.json()["character"]["dossier_name"], "Nyssa")

        # Another user cannot fetch or delete this character
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(
                reverse("spacemarches:api_character_detail", kwargs={"pk": char_id})
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(
                reverse("spacemarches:api_character_detail", kwargs={"pk": char_id})
            ).status_code,
            404,
        )

    def test_roster_upload_exports_xss_escape_and_delete(self):
        self.client.force_login(self.user)
        xss_payload = make_sample_point_buy_payload(
            name="<script>alert(1)</script>Kestrel",
            concept="<b>Courier</b>",
        )
        uploaded = SimpleUploadedFile(
            "kestrel-point-buy.json",
            json.dumps(xss_payload).encode("utf-8"),
            content_type="application/json",
        )
        upload_resp = self.client.post(
            reverse("spacemarches:character_roster"),
            {"character_json": uploaded, "dossier_id": str(self.dossier.pk)},
        )
        self.assertEqual(upload_resp.status_code, 302)

        ch = GeneratedCharacter.objects.filter(user=self.user).order_by("-pk").first()
        self.assertIsNotNone(ch)
        self.assertEqual(ch.dossier_id, self.dossier.pk)

        html_doc = export_generated_character_html(ch)
        self.assertNotIn("<script>alert(1)</script>", html_doc)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_doc)

        md_doc = export_generated_character_markdown(ch)
        self.assertIn("Kestrel", md_doc)
        self.assertIn("Splicer", md_doc)

        for fmt, content_sub in [("html", b"<!doctype html>"), ("md", b"Aptitudes"), ("json", b"point-buy-exported")]:
            exp = self.client.get(
                reverse("spacemarches:character_export", kwargs={"pk": ch.pk}) + f"?format={fmt}"
            )
            self.assertEqual(exp.status_code, 200)
            self.assertIn(content_sub, exp.content)

        del_resp = self.client.post(reverse("spacemarches:character_delete", kwargs={"pk": ch.pk}))
        self.assertEqual(del_resp.status_code, 302)
        self.assertFalse(GeneratedCharacter.objects.filter(pk=ch.pk).exists())

    def test_extract_point_buy_summary_resolves_meshnet_v2_designs_and_tagged_strings(self):
        payload = {
            "type": "point-buy-exported",
            "createdAt": "2026-11-25T12:00:00Z",
            "packs": {
                "ep-crb": {
                    "name": "i_EP2e Core Rulebook",
                    "designs": {
                        "biologicalBody": {
                            "k001": {"name": "i_Ghost"},
                        },
                        "trait": {
                            "tr1": {"name": "i_Situational Awareness"},
                        },
                        "epsilonSleight": {
                            "ep1": {"name": "i_Neural Shunt"},
                        },
                    },
                }
            },
            "pointBuy": {
                "name": "i_Nyx",
                "fullName": "i_Nyx Vesper",
                "concept": "m_Async courier",
                "egoType": "i_Neo-Avian",
                "flexPoints": 1,
                "aptitudes": {"cog": 15, "int": 20, "ref": 15, "sav": 10, "som": 10, "wil": 20},
                "morphs": {"m1": {"design": {"uid": "ep-crb:biologicalBody:k001"}}},
                "egoTraits": {"t1": {"design": {"uid": "ep-crb:trait:tr1"}}},
                "sleights": {"s1": {"design": {"uid": "ep-crb:epsilonSleight:ep1"}}},
            },
        }
        summary = extract_point_buy_summary(payload)
        self.assertEqual(summary["character_name"], "Nyx")
        self.assertEqual(summary["concept"], "Async courier")
        self.assertEqual(summary["morphs"], ["Ghost"])
        self.assertEqual(summary["traits"], ["Situational Awareness"])
        self.assertEqual(summary["sleights"], ["Neural Shunt"])


class CrossModelSheetSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sheet_pilot", password="pw12345!")
        self.dossier = CharacterDossier.objects.create(
            user=self.user,
            character_name="Nyx Vesper",
            slug="nyx-vesper",
        )
        self.payload = {
            "type": "point-buy-exported",
            "createdAt": "2026-11-25T12:00:00Z",
            "packs": {
                "ep-crb": {
                    "name": "i_EP2e Core Rulebook",
                    "designs": {
                        "skillPack": {
                            "E9GLwW0z0fKLJSyd": {"name": "m_aUDYLT", "skillPackType": "faction"},
                        },
                        "biologicalBody": {
                            "k001": {"name": "i_Splicer"},
                        },
                    },
                }
            },
            "pointBuy": {
                "name": "i_Nyx Vesper",
                "fullName": "i_Nyx Vesper-4",
                "concept": "m_Orbital scavenger",
                "egoType": "i_Transhuman",
                "gender": "i_Nonbinary",
                "museName": "i_Iris",
                "aptitudes": {"cog": 15, "int": 20, "ref": 15, "sav": 10, "som": 15, "wil": 15},
                "skillPacks": {
                    "faction": {"design": {"uid": "skillPack:ep-crb:E9GLwW0z0fKLJSyd"}, "skills": {}},
                },
                "morphs": {"m1": {"design": {"uid": "ep-crb:biologicalBody:k001"}}},
            },
        }
        self.sheet = GeneratedCharacter.objects.create(
            user=self.user,
            dossier=self.dossier,
            character_name="Nyx Vesper",
            source_system=GeneratedCharacter.SOURCE_POINT_BUY_V2,
            raw_data=self.payload,
            summary=extract_point_buy_summary(self.payload),
        )

    def test_hashed_skill_pack_name_resolves_cleanly(self):
        self.assertEqual(self.sheet.summary["skill_packs"]["faction"], "Brinker")

    def test_sheet_reminders_pending_sync_and_profile_update_across_models(self):
        from spacemarches.models import EclipsePhaseCensus
        from spacemarches.services.census_service import create_census, save_census_answer

        census = create_census(
            self.user,
            character_name="Nyx Vesper",
            dossier=self.dossier,
            character=self.sheet,
        )
        self.client.force_login(self.user)

        # Inline reminders appear on both Census and Dossier
        census_html = self.client.get(reverse("spacemarches:census_detail", kwargs={"pk": census.pk})).content.decode("utf-8")
        dossier_html = self.client.get(reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug})).content.decode("utf-8")
        self.assertIn("Sheet Reminder", census_html)
        self.assertIn("Brinker", census_html)
        self.assertIn("Change Sheet Option", census_html)
        self.assertIn("Sheet Reminder", dossier_html)
        self.assertIn("Iris", dossier_html)
        self.assertIn('form.getAttribute("action")', dossier_html)
        self.assertNotIn("fetch(form.action", dossier_html)

        # Backdate sheet baseline cleanly so rapid Windows test ticks reliably register newer Census edits
        from datetime import timedelta
        from django.utils import timezone
        GeneratedCharacter.objects.filter(pk=self.sheet.pk).update(updated_at=timezone.now() - timedelta(seconds=5))
        self.sheet.refresh_from_db()

        # Updating a sheet-tracked Census answer and character name surfaces Pending Sync
        save_census_answer(census, "6", "Left the Brinker commune to join Anarchists.")
        census.character_name = "Nyx Anarch"
        census.save()

        roster_html = self.client.get(reverse("spacemarches:character_roster")).content.decode("utf-8")
        self.assertIn("Pending Sync", roster_html)
        self.assertIn("Pending Census / Dossier Updates", roster_html)

        census_html_pending = self.client.get(reverse("spacemarches:census_detail", kwargs={"pk": census.pk})).content.decode("utf-8")
        self.assertIn("Pending Census / Dossier Changes Since Last Sheet Sync", census_html_pending)

        # Switch Faction from Brinker -> Anarchist and update name across Sheet, Dossier & Census
        sync_url = reverse("spacemarches:character_sync_profile", kwargs={"pk": self.sheet.pk})
        post_resp = self.client.post(
            sync_url,
            {
                "character_name": "Nyx Anarch",
                "skill_pack_faction": "o5uyqu81YM17HO7G",
                "muse_name": "Iris-2",
                "sync_linked_names": "1",
                "source": "census",
                "next": reverse("spacemarches:census_detail", kwargs={"pk": census.pk}),
            },
        )
        self.assertEqual(post_resp.status_code, 302)

        self.sheet.refresh_from_db()
        self.dossier.refresh_from_db()
        census.refresh_from_db()

        self.assertEqual(self.sheet.character_name, "Nyx Anarch")
        self.assertEqual(self.sheet.summary["skill_packs"]["faction"], "Anarchist")
        self.assertEqual(self.sheet.summary["muse_name"], "Iris-2")
        self.assertEqual(
            self.sheet.raw_data["pointBuy"]["skillPacks"]["faction"]["design"]["uid"],
            "skillPack:ep-crb:o5uyqu81YM17HO7G",
        )
        self.assertEqual(self.dossier.character_name, "Nyx Anarch")
        self.assertEqual(census.character_name, "Nyx Anarch")

        # Pending notice cleared after sync checkpoint
        census_html_after = self.client.get(reverse("spacemarches:census_detail", kwargs={"pk": census.pk})).content.decode("utf-8")
        self.assertNotIn("Pending Census / Dossier Changes Since Last Sheet Sync", census_html_after)

    def test_dossier_section_navigator_unpacked_meshnet_tools_and_narrative_sync(self):
        from spacemarches.models import EclipsePhaseCensus
        from spacemarches.services.census_service import create_census, save_census_answer

        census = create_census(
            self.user,
            character_name="Nyx Vesper",
            dossier=self.dossier,
            character=self.sheet,
        )
        # Player-authored custom prose on Census [6] must NOT be overwritten
        save_census_answer(census, "6", "I stayed loyal to my Anarchist cell.")

        self.client.force_login(self.user)
        dossier_html = self.client.get(
            reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug})
        ).content.decode("utf-8")
        self.assertIn('id="sm-dossier-drawer"', dossier_html)
        self.assertIn('id="sm-dossier-drawer-fab"', dossier_html)
        self.assertIn('id="sm-dossier-nav-search"', dossier_html)
        self.assertIn("Sections &amp; Focus", dossier_html)
        self.assertIn('id="dossier-q-1"', dossier_html)

        sync_url = reverse("spacemarches:character_sync_profile", kwargs={"pk": self.sheet.pk})
        post_resp = self.client.post(
            sync_url,
            {
                "primary_morph": "Bouncer",
                "aptitude_template": "inquirer",
                "flex_points": "2",
                "rep_c-rep": "45",
                "motivation_cause": "Expose Firewall secrets",
                "motivation_support": "0",
                "languages": "English, Cantonese",
                "description": "Freefall orbital scout.",
                "sync_to_narratives": "1",
                "source": "dossier",
                "next": reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug}),
            },
        )
        self.assertEqual(post_resp.status_code, 302)

        self.sheet.refresh_from_db()
        census.refresh_from_db()
        self.dossier.refresh_from_db()

        self.assertEqual(self.sheet.raw_data.get("type"), "point-buy-exported")
        self.assertEqual(self.sheet.raw_data["pointBuy"]["aptitudeTemplate"], "inquirer")
        self.assertEqual(self.sheet.raw_data["pointBuy"]["aptitudes"]["cog"], 20)
        self.assertEqual(self.sheet.raw_data["pointBuy"]["flexPoints"], 2)
        self.assertEqual(self.sheet.summary["morphs"], ["Bouncer"])
        self.assertEqual(self.sheet.summary["reputations"].get("c-rep"), 45)
        self.assertIn("- Oppose: Expose Firewall secrets", self.sheet.summary["motivations"])
        self.assertEqual(self.sheet.summary["languages"], ["English", "Cantonese"])
        self.assertEqual(self.sheet.summary["description"], "Freefall orbital scout.")

        # API detail endpoint returns valid PointBuyExported JSON
        api_resp = self.client.get(reverse("spacemarches:api_character_detail", kwargs={"pk": self.sheet.pk}))
        self.assertEqual(api_resp.status_code, 200)
        api_raw = api_resp.json()["character"]["raw_data"]
        self.assertEqual(api_raw["type"], "point-buy-exported")
        self.assertEqual(api_raw["pointBuy"]["aptitudes"]["cog"], 20)

        # sync_to_narratives fills blank prompts but preserves custom player prose
        self.assertEqual(census.responses["6"]["answer"], "I stayed loyal to my Anarchist cell.")
        self.assertIn("Bouncer", census.responses["3"]["answer"])
        self.assertIn("Expose Firewall secrets", census.responses["10"]["answer"])
        self.assertIn("Bouncer", self.dossier.responses["3"]["answer"])
        self.assertIn("c-rep: 45", self.dossier.responses["6.2g"]["answer"])

        # Terminal bridge uses PointBuyExported wrapper & bidirectional IndexedDB sync
        mesh_html = self.client.get(reverse("spacemarches:meshnet")).content.decode("utf-8")
        self.assertIn("wrapPointBuyExported", mesh_html)
        self.assertIn("putPointBuyDraft", mesh_html)
        self.assertIn("pendingLoadId", mesh_html)
