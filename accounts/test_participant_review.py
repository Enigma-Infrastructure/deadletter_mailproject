from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from letters.access_policy import ContentAccess, can_read_request
from .models import User
from .services import review_participant, viewer_for_user

class ParticipantReviewTests(TestCase):
    def setUp(self):
        self.reviewer = User.objects.create_superuser(username='organizer', password='Review-strong-79!')
        self.participant = User.objects.create_user(username='participant')

    def test_transitions_record_review_without_granting_admin(self):
        for status in ('approved', 'rejected', 'suspended'):
            reviewed = review_participant(reviewer=self.reviewer, participant_id=self.participant.pk, status=status)
            self.assertEqual(reviewed.participant_status, status)
            self.assertEqual(reviewed.participant_reviewed_by, self.reviewer)
            self.assertIsNotNone(reviewed.participant_reviewed_at)
            self.assertFalse(reviewed.is_staff or reviewed.is_superuser)
            self.assertTrue(reviewed.is_active)

    def test_unauthorized_and_invalid_actions(self):
        for actor in (AnonymousUser(), self.participant):
            with self.assertRaises(PermissionDenied):
                review_participant(reviewer=actor, participant_id=self.participant.pk, status='approved')
        with self.assertRaises(ValidationError):
            review_participant(reviewer=self.reviewer, participant_id=self.participant.pk, status='unknown')
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.participant_status, 'pending')

    def test_staff_requires_explicit_permission_and_current_active_state(self):
        staff = User.objects.create_user(username='reviewer', is_staff=True)
        with self.assertRaises(PermissionDenied):
            review_participant(reviewer=staff, participant_id=self.participant.pk, status='approved')
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='change_user'))
        review_participant(reviewer=staff, participant_id=self.participant.pk, status='approved')
        User.objects.filter(pk=staff.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            review_participant(reviewer=staff, participant_id=self.participant.pk, status='rejected')

    def test_revocation_with_existing_session_and_stale_user(self):
        self.client.force_login(self.participant)
        access = ContentAccess(visibility='participants_only')
        for status in ('pending', 'approved', 'rejected', 'suspended'):
            User.objects.filter(pk=self.participant.pk).update(participant_status=status)
            self.assertEqual(can_read_request(viewer_for_user(self.participant), access), status == 'approved')
            response = self.client.get(reverse('participant_status'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['status'], status)
        User.objects.filter(pk=self.participant.pk).update(participant_status='approved', is_active=False)
        self.assertFalse(viewer_for_user(self.participant).approved)
        self.assertFalse(viewer_for_user(AnonymousUser()).approved)

    def test_admin_queue_filters_and_action(self):
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('admin:accounts_user_changelist'), {'participant_status__exact': 'pending'})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('admin:accounts_user_changelist'), {'action': 'approve_participants', '_selected_action': [str(self.participant.pk)], 'index': '0'})
        self.assertEqual(response.status_code, 302)
        self.participant.refresh_from_db()
        self.assertEqual(self.participant.participant_status, 'approved')
        self.client.force_login(self.participant)
        self.assertNotEqual(self.client.get(reverse('admin:accounts_user_changelist')).status_code, 200)
