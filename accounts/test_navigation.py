from django.contrib.auth.models import Permission
from django.test import Client, TestCase
from django.urls import reverse
from .models import User

class AccountNavigationTests(TestCase):
    def test_anonymous_home_and_login_offer_registration(self):
        for name in ('home', 'login'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'href="' + reverse('register') + '"')
                self.assertNotContains(response, 'href="' + reverse('account_preferences') + '"')
        home = self.client.get(reverse('home'))
        self.assertContains(home, 'New accounts start pending organizer approval.')
        self.assertContains(home, 'Participant-only protection is not yet implemented')

    def test_home_to_registration_journey(self):
        self.assertContains(self.client.get(reverse('home')), 'Register')
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/register.html')
        self.assertContains(response, 'Create pending account')

    def test_account_navigation_for_all_participation_states(self):
        user = User.objects.create_user(username='participant')
        self.client.force_login(user)
        for status in ('pending', 'approved', 'rejected', 'suspended'):
            User.objects.filter(pk=user.pk).update(participant_status=status)
            with self.subTest(status=status):
                response = self.client.get(reverse('home'))
                for name in ('participant_status', 'account_preferences'):
                    self.assertContains(response, 'href="' + reverse(name) + '"')
                self.assertNotContains(response, 'href="' + reverse('register') + '"')
                self.assertNotContains(response, 'href="' + reverse('admin_hub') + '"')
        self.assertRedirects(self.client.get(reverse('register')), reverse('participant_status'))

    def test_admin_hub_account_links_respect_permissions(self):
        staff = User.objects.create_user(username='staff', is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse('admin_hub'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Review participants')
        self.assertNotContains(response, 'Registration sources')
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='change_user'))
        response = self.client.get(reverse('admin_hub'))
        self.assertContains(response, 'Review participants')
        self.assertNotContains(response, 'Registration sources')
        staff.user_permissions.add(Permission.objects.get(content_type__app_label='accounts', codename='view_registrationsource'))
        self.assertContains(self.client.get(reverse('admin_hub')), 'Registration sources')

    def test_superuser_navigation_and_participant_exclusion(self):
        admin = User.objects.create_superuser(username='admin', password='Navigation-79!')
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse('home')), 'href="' + reverse('admin_hub') + '"')
        response = self.client.get(reverse('admin_hub'))
        self.assertContains(response, 'Review participants')
        self.assertContains(response, 'Registration sources')
        user = User.objects.create_user(username='ordinary', participant_status='approved')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('admin_hub')).status_code, 302)

    def test_logout_form_requires_csrf_and_post(self):
        user = User.objects.create_user(username='logout-user')
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.get(reverse('home'))
        self.assertContains(response, 'action="' + reverse('logout') + '"')
        self.assertNotContains(response, 'href="' + reverse('logout') + '"')
        self.assertEqual(client.get(reverse('logout')).status_code, 405)
        self.assertEqual(client.post(reverse('logout')).status_code, 403)
        token = client.cookies['csrftoken'].value
        response = client.post(reverse('logout'), {'csrfmiddlewaretoken': token})
        self.assertIn(response.status_code, (200, 302))
        self.assertNotIn('_auth_user_id', client.session)
