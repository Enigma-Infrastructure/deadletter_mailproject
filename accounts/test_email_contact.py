from django import forms
from django.contrib import admin
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from .contact import update_contact_email
from .forms import PreferencesForm, RegistrationForm
from .models import User


class EmailContactTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='contact-user', email='old@example.org', password='Contact-password-79!')

    def seed_verified(self):
        User.objects.filter(pk=self.user.pk).update(email_verified=True)
        self.user.refresh_from_db()

    def test_registration_email_optional_validated_and_never_verified(self):
        for number, email in enumerate(('', 'optional@example.org')):
            form = RegistrationForm(data=dict(username=f'new-{number}', email=email, password1='New-contact-password-79!', password2='New-contact-password-79!', default_request_visibility='public', default_body_visibility='public', email_verified='true'))
            self.assertTrue(form.is_valid(), form.errors)
            user = form.save()
            self.assertEqual(user.email, email)
            self.assertFalse(user.email_verified)
            self.assertEqual(user.participant_status, 'pending')
        form = RegistrationForm(data={'email': 'invalid'})
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_password_required_and_only_current_user_changes(self):
        other = User.objects.create_user(username='other-contact', email='other@example.org')
        self.client.force_login(self.user)
        url = reverse('account_contact')
        response = self.client.post(url, {'email': 'new@example.org', 'current_password': 'wrong'})
        self.assertContains(response, 'Your current password was not accepted.')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old@example.org')
        response = self.client.post(url, {'email': 'new@example.org', 'current_password': 'Contact-password-79!', 'user_id': other.pk, 'email_verified': 'true', 'participant_status': 'approved'})
        self.assertRedirects(response, url)
        self.user.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.org')
        self.assertFalse(self.user.email_verified)
        self.assertEqual(self.user.participant_status, 'pending')
        self.assertEqual(other.email, 'other@example.org')

    def test_same_email_preserves_then_change_and_remove_invalidate(self):
        self.seed_verified()
        update_contact_email(actor=self.user, email='old@example.org', current_password='Contact-password-79!')
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        update_contact_email(actor=self.user, email='new@example.org', current_password='Contact-password-79!')
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)
        self.seed_verified()
        update_contact_email(actor=self.user, email='', current_password='Contact-password-79!')
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, '')
        self.assertFalse(self.user.email_verified)

    def test_stale_save_and_preferences_do_not_restore_email_or_flag(self):
        self.seed_verified()
        stale = User.objects.get(pk=self.user.pk)
        update_contact_email(actor=self.user, email='new@example.org', current_password='Contact-password-79!')
        stale.first_name = 'Changed'
        stale.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.org')
        self.assertFalse(self.user.email_verified)
        form = PreferencesForm(data={'default_request_visibility': 'participants_only', 'default_body_visibility': 'public'}, instance=stale)
        self.assertTrue(form.is_valid())
        form.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.org')
        self.assertFalse(self.user.email_verified)

    def test_admin_save_invalidates_and_verification_is_readonly(self):
        self.seed_verified()
        organizer = User.objects.create_superuser(username='contact-admin', password='Admin-test-79!')
        request = RequestFactory().post('/')
        request.user = organizer
        model_admin = admin.site._registry[User]
        self.assertIn('email_verified', model_admin.get_readonly_fields(request, self.user))
        self.user.email = 'admin-edit@example.org'
        model_admin.save_model(request, self.user, None, True)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_contact_login_csrf_cache_and_navigation(self):
        url = reverse('account_contact')
        self.assertEqual(self.client.get(url).status_code, 302)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.get(url)
        self.assertContains(response, 'class="card"')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(client.post(url, {'email': 'attempt@example.org', 'current_password': 'Contact-password-79!'}).status_code, 403)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('account_preferences')), 'href="' + url + '"')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_all_recovery_routes_are_inert(self):
        original = self.user.password
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        routes = [reverse('password_reset'), reverse('password_reset_done'), reverse('password_reset_complete'), reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})]
        for route in routes:
            for method in (self.client.get, self.client.post):
                with self.subTest(route=route, method=method.__name__):
                    response = method(route, {'email': self.user.email, 'new_password1': 'Changed-password-79!', 'new_password2': 'Changed-password-79!'})
                    self.assertEqual(response.status_code, 503)
        self.user.refresh_from_db()
        self.assertEqual(self.user.password, original)
        self.assertEqual(len(mail.outbox), 0)
