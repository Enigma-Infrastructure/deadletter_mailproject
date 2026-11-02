from datetime import timedelta
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from .models import RegistrationSource, User

class RegistrationTests(TestCase):
    def payload(self, **overrides):
        data = dict(username='newperson', password1='Long-random-Register-79!', password2='Long-random-Register-79!', default_request_visibility='public', default_body_visibility='participants_only')
        data.update(overrides)
        return data

    def test_registration_is_pending_and_ignores_privilege_fields(self):
        response = self.client.post(reverse('register'), self.payload(participant_status='approved', is_staff='1', is_superuser='1', is_collaborator='1', participant_reviewed_by='1'))
        self.assertRedirects(response, reverse('participant_status'))
        user = User.objects.get(username='newperson')
        self.assertEqual(user.participant_status, 'pending')
        self.assertFalse(user.is_staff or user.is_superuser or user.is_collaborator)
        self.assertIsNone(user.participant_reviewed_by_id)
        self.assertIsNone(user.participant_reviewed_at)
        self.assertEqual(str(user.pk), self.client.session['_auth_user_id'])
        self.assertEqual(user.default_body_visibility, 'participants_only')

    def test_qr_initial_and_manual_source_attribution(self):
        RegistrationSource.objects.create(code='qr', label='QR')
        manual = RegistrationSource.objects.create(code='manual', label='Manual')
        url = reverse('register') + '?source=qr'
        self.assertEqual(self.client.get(url).context['form'].initial['source'], 'qr')
        self.client.post(url, self.payload(source='manual'))
        user = User.objects.get(username='newperson')
        self.assertEqual(user.registration_source, manual)
        self.assertEqual(user.participant_status, 'pending')

    def test_invalid_inactive_expired_sources(self):
        RegistrationSource.objects.create(code='inactive', label='Inactive', is_active=False)
        RegistrationSource.objects.create(code='expired', label='Expired', expires_at=timezone.now() - timedelta(seconds=1))
        for code in ('missing', 'inactive', 'expired'):
            with self.subTest(code=code):
                response = self.client.post(reverse('register'), self.payload(source=code))
                self.assertIn('source', response.context['form'].errors)
                self.assertFalse(User.objects.filter(username='newperson').exists())

    def test_invalid_visibility_and_csrf(self):
        response = self.client.post(reverse('register'), self.payload(default_body_visibility='friends'))
        self.assertIn('default_body_visibility', response.context['form'].errors)
        self.assertEqual(Client(enforce_csrf_checks=True).post(reverse('register'), self.payload()).status_code, 403)

    def test_defaults_and_existing_account_redirect(self):
        form = self.client.get(reverse('register')).context['form']
        self.assertEqual(form['default_request_visibility'].value(), 'public')
        self.assertEqual(form['default_body_visibility'].value(), 'public')
        user = User.objects.create_user(username='existing')
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse('register')), reverse('participant_status'))
