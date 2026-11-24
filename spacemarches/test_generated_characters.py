import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
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
