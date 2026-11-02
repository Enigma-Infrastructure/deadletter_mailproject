from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import ReputationEvent
from media_app.models import MediaItem
from people.models import Person, Place
from .models import LetterConcept, LetterHop, LetterInstance, Stamp, StampUpdate


class RecipientIntakeTests(TestCase):
    def payload(self, **overrides):
        data = {"nickname": "Test Pirate", "pirate_address": "Test Cafe",
                "city": "Somerville", "write_about": "First prompt",
                "email": "first@example.com"}
        data.update(overrides)
        return data

    def submit(self, **overrides):
        return self.client.post(reverse("request_a_letter"), self.payload(**overrides))

    def test_first_submission_creates_recipient_and_request(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        person = Person.objects.get()
        self.assertEqual(person.email, "first@example.com")
        self.assertEqual(person.write_about, "First prompt")
        self.assertEqual(LetterConcept.objects.get().created_for, person)

    def test_repeat_submission_preserves_profile_and_new_prompt(self):
        self.submit()
        response = self.submit(email="replacement@example.com", write_about="New request prompt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Person.objects.count(), 1)
        self.assertEqual(Place.objects.count(), 1)
        person = Person.objects.get()
        self.assertEqual(person.email, "first@example.com")
        self.assertEqual(person.write_about, "First prompt")
        self.assertEqual(LetterConcept.objects.filter(created_for=person).count(), 2)
        self.assertTrue(LetterConcept.objects.filter(write_prompt="New request prompt").exists())

    def test_blank_repeat_does_not_erase_profile(self):
        self.submit()
        self.submit(email="", write_about="")
        person = Person.objects.get()
        self.assertEqual(person.email, "first@example.com")
        self.assertEqual(person.write_about, "First prompt")

    def test_invalid_submission_creates_nothing(self):
        response = self.submit(email="not-an-email")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Person.objects.exists())
        self.assertFalse(Place.objects.exists())
        self.assertFalse(LetterConcept.objects.exists())


class LetterPrivacyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.private = LetterInstance.objects.create(
            is_public=False, body_text="PRIVATE-BODY-MARKER", status="waiting_carrier",
        )
        self.public = LetterInstance.objects.create(
            is_public=True, body_text="PUBLIC-BODY-MARKER", status="waiting_carrier",
        )
        self.private_stamp = Stamp.objects.create(letter=self.private)
        self.public_stamp = Stamp.objects.create(letter=self.public)

    def scan_url(self, stamp):
        return reverse("scan_stamp", kwargs={"number": stamp.number})

    def test_private_detail_routes_return_404(self):
        for route in ("letter_public", "letter_print", "letter_write_confirm"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"code": self.private.code}))
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, "PRIVATE-BODY-MARKER", status_code=404)
        self.assertEqual(self.client.get(self.scan_url(self.private_stamp)).status_code, 404)

    def test_private_scan_post_has_no_side_effects(self):
        response = self.client.post(self.scan_url(self.private_stamp), {
            "kind": "delivered", "note": "Attempt",
            "place_name": "Unexpected Place", "city": "Somerville",
        })
        self.assertEqual(response.status_code, 404)
        self.private.refresh_from_db()
        self.assertEqual(self.private.status, "waiting_carrier")
        for model in (StampUpdate, LetterHop, MediaItem, ReputationEvent, Place):
            self.assertEqual(model.objects.count(), 0)

    def test_public_detail_routes_still_work(self):
        for route in ("letter_public", "letter_print", "letter_write_confirm"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"code": self.public.code}))
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(self.scan_url(self.public_stamp)).status_code, 200)

    def test_public_scan_update_still_works_anonymously(self):
        response = self.client.post(self.scan_url(self.public_stamp), {"kind": "delivered", "note": "Arrived"})
        self.assertEqual(response.status_code, 302)
        self.public.refresh_from_db()
        self.assertEqual(self.public.status, "delivered")
        self.assertEqual(StampUpdate.objects.get().stamp, self.public_stamp)
        self.assertEqual(LetterHop.objects.get().letter, self.public)
        self.assertFalse(ReputationEvent.objects.exists())

    def test_lists_and_api_exclude_private_letters(self):
        for route in ("letter_read_list", "desk_read_list", "carry_list", "letters_in_my_area_api"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, self.private.code)
                self.assertNotContains(response, "PRIVATE-BODY-MARKER")

    def test_inactive_stamp_is_inaccessible(self):
        self.public_stamp.is_active = False
        self.public_stamp.save(update_fields=["is_active"])
        url = self.scan_url(self.public_stamp)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"kind": "spotted"}).status_code, 404)
        self.assertFalse(StampUpdate.objects.exists())

    def test_staff_admin_access_is_preserved_without_public_bypass(self):
        user = get_user_model().objects.create_superuser(
            username="test-admin", email="admin@example.com", password="test-only-password",
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("admin:letters_letterinstance_change", args=[self.private.pk])).status_code, 200)
        self.assertEqual(self.client.get(self.scan_url(self.private_stamp)).status_code, 404)
        self.assertEqual(self.client.post(self.scan_url(self.private_stamp), {"kind": "delivered"}).status_code, 404)
        self.assertFalse(StampUpdate.objects.exists())

    def test_anonymous_print_confirmation_is_blocked(self):
        self.assertEqual(self.client.post(reverse("print_confirm"), {"letters": [self.public.pk]}).status_code, 302)
        self.public.refresh_from_db()
        self.assertTrue(self.public.needs_printing)
        self.assertEqual(self.public.status, "waiting_carrier")
