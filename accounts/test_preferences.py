from django.test import TestCase
from django.urls import reverse
from .models import User

class PreferenceTests(TestCase):
    def test_requires_login(self):
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(reverse('account_preferences')).status_code, 302)
        self.assertEqual(self.client.get(reverse('participant_status')).status_code, 302)

    def test_only_current_accounts_defaults_change(self):
        user = User.objects.create_user(username='owner')
        other = User.objects.create_user(username='other')
        original_other = User.objects.values().get(pk=other.pk)
        original_user = User.objects.values().get(pk=user.pk)
        self.client.force_login(user)
        response = self.client.post(reverse('account_preferences'), {'default_request_visibility': 'participants_only', 'default_body_visibility': 'participants_only', 'user_id': other.pk, 'participant_status': 'approved', 'is_staff': '1'})
        self.assertRedirects(response, reverse('account_preferences'))
        changed = User.objects.values().get(pk=user.pk)
        self.assertEqual(changed['default_request_visibility'], 'participants_only')
        self.assertEqual(changed['default_body_visibility'], 'participants_only')
        for field in original_user.keys() - {'default_request_visibility', 'default_body_visibility', 'last_login'}:
            self.assertEqual(changed[field], original_user[field])
        self.assertEqual(User.objects.values().get(pk=other.pk), original_other)

    def test_unknown_visibility_rejected(self):
        user = User.objects.create_user(username='owner')
        self.client.force_login(user)
        response = self.client.post(reverse('account_preferences'), {'default_request_visibility': 'friends', 'default_body_visibility': 'public'})
        self.assertIn('default_request_visibility', response.context['form'].errors)
        user.refresh_from_db()
        self.assertEqual(user.default_request_visibility, 'public')
