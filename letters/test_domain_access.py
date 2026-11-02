from itertools import product

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .access_policy import ContentAccess, Viewer, can_read_body, can_read_request
from .domain_access import (can_read_letter_address, can_read_request_address, can_read_saved_letter, can_read_saved_request, persisted_viewer, readable_letters, readable_requests)
from .models import Letter, LetterRequest


class DomainAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='participant', participant_status='approved')
        self.parent = LetterRequest.objects.create(prompt='Private prompt')
        self.letter = Letter.objects.create(request=self.parent, body_text='Private body')

    def test_database_audience_matrix_matches_pure_policy(self):
        for approved in (False, True):
            viewer = self.user if approved else AnonymousUser()
            pure_viewer = Viewer(True, True, 'approved') if approved else Viewer()
            for rv, bv, rr, br, rp, bp in product(('public', 'participants_only'), ('public', 'participants_only'), (False, True), (False, True), (False, True), (False, True)):
                with self.subTest(approved=approved, rv=rv, bv=bv, rr=rr, br=br, rp=rp, bp=bp):
                    LetterRequest.objects.filter(pk=self.parent.pk).update(requested_visibility=rv, automatically_restricted=rr, is_published=rp)
                    Letter.objects.filter(pk=self.letter.pk).update(requested_visibility=bv, automatically_restricted=br, is_published=bp)
                    ra, ba = ContentAccess(rv, rr, rp), ContentAccess(bv, br, bp)
                    expected_request = can_read_request(pure_viewer, ra)
                    expected_body = can_read_body(pure_viewer, ra, ba)
                    self.assertEqual(can_read_saved_request(viewer, self.parent.pk), expected_request)
                    self.assertEqual(can_read_saved_letter(viewer, self.letter.pk), expected_body)
                    self.assertEqual(can_read_request_address(viewer, self.parent.pk), approved and expected_request)
                    self.assertEqual(can_read_letter_address(viewer, self.letter.pk), approved and expected_body)

    def test_unpublished_backfill_defaults_remain_hidden(self):
        for user in (None, AnonymousUser(), self.user):
            self.assertFalse(can_read_saved_request(user, self.parent.pk))
            self.assertFalse(can_read_saved_letter(user, self.letter.pk))
            self.assertFalse(can_read_request_address(user, self.parent.pk))
            self.assertFalse(can_read_letter_address(user, self.letter.pk))

    def test_approval_is_read_from_database_not_stale_user_instance(self):
        LetterRequest.objects.update(is_published=True)
        Letter.objects.update(is_published=True)
        self.assertTrue(can_read_saved_letter(self.user, self.letter.pk))
        for status in ('pending', 'rejected', 'suspended', 'unknown'):
            get_user_model().objects.filter(pk=self.user.pk).update(participant_status=status)
            self.assertEqual(self.user.participant_status, 'approved')
            self.assertFalse(can_read_saved_letter(self.user, self.letter.pk))
            self.assertFalse(can_read_request_address(self.user, self.parent.pk))
        get_user_model().objects.filter(pk=self.user.pk).update(participant_status='approved', is_active=False)
        self.assertFalse(persisted_viewer(self.user).approved)
        self.assertFalse(can_read_saved_letter(self.user, self.letter.pk))

    def test_staff_superuser_owner_and_writer_are_not_audience_bypasses(self):
        get_user_model().objects.filter(pk=self.user.pk).update(is_staff=True, is_superuser=True, participant_status='pending')
        LetterRequest.objects.update(owner=self.user, submitted_by=self.user, is_published=True)
        Letter.objects.update(writer=self.user, is_published=True)
        self.assertFalse(can_read_saved_request(self.user, self.parent.pk))
        self.assertFalse(can_read_saved_letter(self.user, self.letter.pk))

    def test_standalone_letters_use_their_own_audience(self):
        Letter.objects.filter(pk=self.letter.pk).update(request=None, is_published=True, requested_visibility='public')
        self.assertTrue(can_read_saved_letter(None, self.letter.pk))
        self.assertFalse(can_read_letter_address(None, self.letter.pk))
        self.assertTrue(can_read_letter_address(self.user, self.letter.pk))
        Letter.objects.update(automatically_restricted=True)
        self.assertFalse(can_read_saved_letter(None, self.letter.pk))
        self.assertTrue(can_read_saved_letter(self.user, self.letter.pk))
        Letter.objects.update(is_published=False)
        self.assertFalse(can_read_saved_letter(self.user, self.letter.pk))

    def test_stale_target_objects_do_not_override_persisted_publication(self):
        self.parent.is_published = True
        self.parent.requested_visibility = 'public'
        self.letter.is_published = True
        self.letter.requested_visibility = 'public'
        self.assertFalse(can_read_saved_request(None, self.parent.pk))
        self.assertFalse(can_read_saved_letter(None, self.letter.pk))

    def test_public_prompt_does_not_grant_social_address_access(self):
        LetterRequest.objects.update(is_published=True, requested_visibility='public')
        Letter.objects.update(is_published=True, requested_visibility='public')
        self.assertTrue(can_read_saved_request(None, self.parent.pk))
        self.assertTrue(can_read_saved_letter(None, self.letter.pk))
        self.assertFalse(can_read_request_address(None, self.parent.pk))
        self.assertFalse(can_read_letter_address(None, self.letter.pk))

    def test_filtered_querysets_do_not_duplicate_or_write(self):
        LetterRequest.objects.update(is_published=True)
        Letter.objects.update(is_published=True)
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(list(readable_requests(self.user).values_list('pk', flat=True)), [self.parent.pk])
            self.assertEqual(list(readable_letters(self.user).values_list('pk', flat=True)), [self.letter.pk])
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))

    def test_missing_records_and_deleted_users_fail_closed(self):
        missing = max(self.parent.pk, self.letter.pk) + 100
        self.assertFalse(can_read_saved_request(self.user, missing))
        self.assertFalse(can_read_saved_letter(self.user, missing))
        self.assertFalse(can_read_request_address(self.user, missing))
        self.assertFalse(can_read_letter_address(self.user, missing))
        get_user_model().objects.filter(pk=self.user.pk).delete()
        self.assertFalse(persisted_viewer(self.user).approved)
