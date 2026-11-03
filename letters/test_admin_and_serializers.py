"""Tests for Django Admin registrations and domain serializer representations."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from people.models import Person, Place
from .models import DomainSubmissionReceipt, Letter, LetterConcept, LetterInstance, LetterRequest, Stamp
from .serializers import LetterInstanceSerializer


class AdminAndSerializerTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(
            username="super-admin",
            email="admin@example.org",
            password="AdminPassword123!",
            is_staff=True,
            is_active=True,
            participant_status="approved",
        )
        self.place = Place.objects.create(name="Harbor Books", city="Gloucester", kind="bookstore")
        self.person = Person.objects.create(nickname="Sailor Sam", pirate_place=self.place, city="Gloucester")

        self.concept = LetterConcept.objects.create(
            title="Letter for Sailor Sam",
            write_prompt="Lighthouse stories",
            destination_place=self.place,
            destination_city="Gloucester",
            created_for=self.person,
        )
        self.req = LetterRequest.objects.create(
            prompt="Lighthouse stories",
            recipient=self.person,
            recipient_alias="Sailor Sam",
            destination_place=self.place,
            destination_city="Gloucester",
            destination_label="Harbor Books · Gloucester",
            concept=self.concept,
            legacy_source=self.concept,
            requested_visibility="public",
            is_published=True,
            is_open=True,
        )
        self.letter = Letter.objects.create(
            request=self.req,
            concept=self.concept,
            writer=self.admin_user,
            body_text="Keep the beacon shining bright through the storm.",
            prompt_snapshot="Lighthouse stories",
            recipient=self.person,
            recipient_alias="Sailor Sam",
            destination_place=self.place,
            destination_city="Gloucester",
            destination_label="Harbor Books · Gloucester",
            requested_visibility="public",
            is_published=True,
        )
        self.instance = LetterInstance.objects.create(
            authored_letter=self.letter,
            concept=self.concept,
            recipient=self.person,
            body_text=self.letter.body_text,
            current_place=self.place,
            current_city="Gloucester",
            status="traveling",
            is_public=True,
        )
        self.stamp = Stamp.objects.create(letter=self.instance, is_active=True)
        self.receipt = DomainSubmissionReceipt.objects.create(
            actor=self.admin_user,
            operation="request",
            key_digest="a" * 64,
            payload_digest="b" * 64,
            completed=True,
            request_result=self.req,
        )

    def test_admin_changelist_views_for_domain_models(self):
        self.client.force_login(self.admin_user)

        # 1. LetterRequest admin changelist
        req_changelist = self.client.get(reverse("admin:letters_letterrequest_changelist"))
        self.assertEqual(req_changelist.status_code, 200)
        self.assertContains(req_changelist, "Sailor Sam")

        # 2. Letter admin changelist
        letter_changelist = self.client.get(reverse("admin:letters_letter_changelist"))
        self.assertEqual(letter_changelist.status_code, 200)
        self.assertContains(letter_changelist, "Sailor Sam")

        # 3. DomainSubmissionReceipt admin changelist
        receipt_changelist = self.client.get(reverse("admin:letters_domainsubmissionreceipt_changelist"))
        self.assertEqual(receipt_changelist.status_code, 200)
        self.assertContains(receipt_changelist, self.admin_user.username)

        # 4. LetterInstance admin changelist with authored_letter
        inst_changelist = self.client.get(reverse("admin:letters_letterinstance_changelist"))
        self.assertEqual(inst_changelist.status_code, 200)
        self.assertContains(inst_changelist, self.instance.code)

    def test_admin_hub_surfaces_new_domain_admin_links(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin_hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin:letters_letterrequest_changelist"))
        self.assertContains(response, reverse("admin:letters_letter_changelist"))

    def test_letter_instance_serializer_with_authored_letter(self):
        serializer = LetterInstanceSerializer(self.instance)
        data = serializer.data
        self.assertEqual(data["code"], self.instance.code)
        self.assertEqual(data["body_text"], "Keep the beacon shining bright through the storm.")
        self.assertEqual(data["stamp_numbers"], [self.stamp.number])
        self.assertTrue(data["is_public"])
