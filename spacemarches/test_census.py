import json
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from spacemarches.census import (
    get_all_census_questions,
    get_census_attribution,
    get_census_chapters,
    get_census_meta,
    get_census_question,
    get_chapter_questions,
    load_census_schema,
)
from spacemarches.models import (
    CharacterDossier,
    EclipsePhaseCensus,
    GeneratedCharacter,
    ProtectionAccessLog,
)
from spacemarches.services.census_service import (
    compute_census_stats,
    create_census,
    export_census_html,
    export_census_json,
    export_census_markdown,
    save_census_answer,
)
from spacemarches.services.protection_service import protection_state, set_secret

User = get_user_model()


class CensusSchemaTests(TestCase):
    def test_schema_preserves_community_chapters_and_framing(self):
        schema = load_census_schema()
        meta = get_census_meta()
        self.assertEqual(schema["license"], "CC BY-NC-SA 3.0")
        self.assertIn("ShadowDragon8685", meta["attribution_notice"])
        self.assertIn("GearheadLydia", meta["attribution_notice"])
        self.assertEqual(len(meta["intro_paragraphs"]), 6)
        self.assertTrue(any("Moved Questions" in p or "appendix" in p.lower() for p in meta["appendix_notice"]))
        self.assertGreater(len(meta["tracked_changes"]), 30)
        self.assertGreaterEqual(len(meta["legal_notice"]), 4)
        self.assertTrue(any("Creative Commons Attribution-Noncommercial-Share Alike 3.0" in p for p in meta["legal_notice"]))

        chapters = get_census_chapters(include_appendix=True)
        self.assertEqual(len(chapters), 10)
        self.assertEqual(chapters[0]["id"], "origins")
        self.assertEqual(chapters[-1]["id"], "appendix")
        self.assertTrue(chapters[-1]["is_appendix"])

        all_items = get_all_census_questions(include_sexuality=True, include_appendix=True, answerable_only=False)
        answerable = get_all_census_questions(include_sexuality=True, include_appendix=True, answerable_only=True)
        self.assertEqual(len(all_items), 126)
        self.assertEqual(len(answerable), 124)

        for key in [
            "1", "5", "6", "6.1", "6.1f1", "6.1f4", "6.1j",
            "6.2", "6.2a1", "6.2h", "6.2o",
            "11", "11L", "11x",
            "12", "12A", "12D",
            "13", "13a", "13b", "13c", "13c9", "13d_stub", "13e", "13e5",
            "14", "14h", "15", "15f", "16", "16c",
            "13d", "13d1", "13d6",
        ]:
            self.assertIsNotNone(get_census_question(key), f"Missing schema item {key}")

        q_titans = get_census_question("6.1j")
        self.assertIn("point of Rez", q_titans["primer"])
        q_stub = get_census_question("13d_stub")
        self.assertFalse(q_stub["answerable"])
        self.assertIn("moved to the appendix", q_stub["primer"])

    def test_optional_filtering(self):
        no_app = get_all_census_questions(include_sexuality=True, include_appendix=False, answerable_only=True)
        no_sex = get_all_census_questions(include_sexuality=False, include_appendix=False, answerable_only=True)
        self.assertEqual(len(no_app), 117)  # 124 - 7 appendix items
        self.assertEqual(len(no_sex), 101)  # 117 - (10 in 13c..c9 + 6 in 13e..e5)
        ids_no_sex = {q["id"] for q in no_sex}
        self.assertNotIn("13c", ids_no_sex)
        self.assertNotIn("13e1", ids_no_sex)
        self.assertNotIn("13d1", ids_no_sex)


class CensusServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="census_user", password="pw12345!")
        self.dossier = CharacterDossier.objects.create(
            user=self.user,
            character_name="Nova Kestrel",
            slug="nova-kestrel",
        )
        self.sheet = GeneratedCharacter.objects.create(
            user=self.user,
            dossier=self.dossier,
            character_name="Nova Kestrel",
            source_system=GeneratedCharacter.SOURCE_POINT_BUY_V2,
            raw_data={},
            summary={},
        )

    def test_create_save_clear_and_exports(self):
        census = create_census(
            self.user,
            character_name="",
            dossier=self.dossier,
            character=self.sheet,
        )
        self.assertEqual(census.character_name, "Nova Kestrel")
        self.assertEqual(census.slug, "nova-kestrel")
        self.assertEqual(census.dossier, self.dossier)
        self.assertEqual(census.character, self.sheet)

        saved = save_census_answer(census, "1", "I was on Luna when the uplinks died.", voice="first_person")
        self.assertTrue(saved["answered"])
        self.assertEqual(saved["voice"], "first_person")
        save_census_answer(census, "6.1j", "The TITANs remain an existential dread.", voice="omniscient")

        with self.assertRaises(ValueError):
            save_census_answer(census, "13d_stub", "Not answerable")
        with self.assertRaises(ValueError):
            save_census_answer(census, "999", "Unknown")

        stats = compute_census_stats(census)
        self.assertEqual(stats["answered_count"], 2)
        self.assertEqual(stats["total_questions"], 117)

        md = export_census_markdown(census)
        self.assertIn("# Eclipse Phase Character Questionnaire: Nova Kestrel", md)
        self.assertIn("I was on Luna when the uplinks died.", md)
        self.assertIn("Creative Commons", md)
        self.assertIn("ShadowDragon8685", md)

        # XSS sanitization in HTML export
        save_census_answer(census, "2", '<script>alert("xss")</script> Grown in a vat.')
        html_out = export_census_html(census)
        self.assertNotIn('<script>alert("xss")</script>', html_out)
        self.assertIn("&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;", html_out)

        payload = export_census_json(census)
        self.assertEqual(payload["license"], "CC BY-NC-SA 3.0")
        self.assertEqual(len(payload["responses"]), 3)

        cleared = save_census_answer(census, "1", "   ")
        self.assertFalse(cleared["answered"])
        self.assertEqual(compute_census_stats(census)["answered_count"], 2)


class CensusViewsAndProtectionTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="alice", password="pw12345!")
        self.other = User.objects.create_user(username="bob", password="pw12345!")
        self.st = User.objects.create_user(username="storyteller", password="pw12345!", is_st=True)
        self.dossier = CharacterDossier.objects.create(
            user=self.owner,
            character_name="Vesper Vance",
            slug="vesper-vance",
        )
        self.census = EclipsePhaseCensus.objects.create(
            user=self.owner,
            dossier=self.dossier,
            character_name="Vesper Vance",
            slug="vesper-vance",
        )

    def test_auth_gating_and_user_isolation(self):
        list_url = reverse("spacemarches:census_list")
        detail_url = reverse("spacemarches:census_detail", kwargs={"pk": self.census.pk})
        self.assertEqual(self.client.get(list_url).status_code, 302)
        self.assertEqual(self.client.get(detail_url).status_code, 302)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_walkthrough_navigation_ajax_save_and_appendix_opt_in(self):
        self.client.force_login(self.owner)
        portal_resp = self.client.get(reverse("spacemarches:portal"))
        self.assertContains(portal_resp, reverse("spacemarches:census_list"))
        dossier_resp = self.client.get(reverse("spacemarches:dossier_detail", kwargs={"slug": self.dossier.slug}))
        self.assertContains(dossier_resp, reverse("spacemarches:census_detail", kwargs={"pk": self.census.pk}))

        # Appendix gated off by default
        app_resp = self.client.get(reverse("spacemarches:census_detail", kwargs={"pk": self.census.pk}) + "?chapter=appendix")
        self.assertEqual(app_resp.status_code, 200)
        self.assertContains(app_resp, "Opt In &amp; Show Moved Questions")
        self.assertNotContains(app_resp, "13d1")

        # Opt in to appendix
        self.client.post(
            reverse("spacemarches:census_settings", kwargs={"pk": self.census.pk}),
            {"action": "toggle_appendix", "chapter": "appendix"},
        )
        app_resp2 = self.client.get(reverse("spacemarches:census_detail", kwargs={"pk": self.census.pk}) + "?chapter=appendix")
        self.assertContains(app_resp2, "13d1")

        # AJAX answer save
        ans_url = reverse("spacemarches:census_answer", kwargs={"pk": self.census.pk})
        ajax_resp = self.client.post(
            ans_url,
            data=json.dumps({"question_id": "1", "answer_text": "Escaped Earth orbit.", "voice": "first_person"}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(ajax_resp.status_code, 200)
        payload = ajax_resp.json()
        self.assertTrue(payload["answered"])
        self.assertEqual(payload["stats"]["answered_count"], 1)

        # Exports work
        md_resp = self.client.get(reverse("spacemarches:census_export", kwargs={"pk": self.census.pk}) + "?format=md")
        self.assertEqual(md_resp.status_code, 200)
        self.assertIn("Escaped Earth orbit.", md_resp.content.decode("utf-8"))
        json_resp = self.client.get(reverse("spacemarches:census_export", kwargs={"pk": self.census.pk}) + "?format=json")
        self.assertEqual(json_resp.status_code, 200)
        self.assertEqual(json_resp.json()["character_name"], "Vesper Vance")

    def test_public_review_and_protection_locks(self):
        save_census_answer(self.census, "1", "Classified Fall memory.")
        review_url = reverse("spacemarches:census_review", kwargs={"pk": self.census.pk})

        # Private by default for outsiders
        self.assertEqual(self.client.get(review_url).status_code, 404)

        # Enable public review + secret lock
        self.census.public_view = True
        self.census.protection = GeneratedCharacter.PROTECTION_SECRET
        self.census.save()
        set_secret(self.census, "Which hab burned?", "O'Neill")

        locked_resp = self.client.get(review_url)
        self.assertEqual(locked_resp.status_code, 200)
        self.assertContains(locked_resp, "Which hab burned?")
        self.assertNotContains(locked_resp, "Classified Fall memory.")

        # Unlock via wrong answer fails
        self.client.post(review_url, {"action": "unlock_census", "answer": "wrong"})
        self.assertNotContains(self.client.get(review_url), "Classified Fall memory.")

        # Unlock via right answer reveals and logs access
        self.client.post(review_url, {"action": "unlock_census", "answer": "O'Neill"})
        unlocked_resp = self.client.get(review_url)
        self.assertContains(unlocked_resp, "Classified Fall memory.")
        self.assertTrue(
            ProtectionAccessLog.objects.filter(
                target_kind=ProtectionAccessLog.TARGET_CENSUS,
                target_pk=self.census.pk,
                protection_type=GeneratedCharacter.PROTECTION_SECRET,
            ).exists()
        )

        # ST-Only lock
        self.census.protection = GeneratedCharacter.PROTECTION_ST_ONLY
        self.census.save()
        self.client.force_login(self.other)
        non_st_resp = self.client.get(review_url)
        self.assertContains(non_st_resp, "Storyteller Access Required")
        self.assertNotContains(non_st_resp, "Classified Fall memory.")

        self.client.force_login(self.st)
        st_resp = self.client.get(review_url)
        self.assertContains(st_resp, "Classified Fall memory.")
        self.assertTrue(
            ProtectionAccessLog.objects.filter(
                target_kind=ProtectionAccessLog.TARGET_CENSUS,
                target_pk=self.census.pk,
                viewer=self.st,
                protection_type=GeneratedCharacter.PROTECTION_ST_ONLY,
            ).exists()
        )
        # Owner sees Security Log on census_detail
        self.client.force_login(self.owner)
        owner_detail = self.client.get(reverse("spacemarches:census_detail", kwargs={"pk": self.census.pk}))
        self.assertContains(owner_detail, "Security Log")
        self.assertContains(owner_detail, "storyteller")
