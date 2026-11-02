from html.parser import HTMLParser

from django.test import TestCase
from django.urls import reverse

from .models import User


class MainLayoutParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.children = []

    def handle_starttag(self, tag, attrs):
        if self.stack and self.stack[-1] == 'main':
            self.children.append((tag, dict(attrs)))
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if self.stack and self.stack[-1] == 'main':
            self.children.append((tag, dict(attrs)))

    def handle_endtag(self, tag):
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            del self.stack[index:]


class AccountLayoutTests(TestCase):
    def assert_single_card(self, response):
        self.assertEqual(response.status_code, 200)
        parser = MainLayoutParser()
        parser.feed(response.content.decode())
        self.assertEqual(len(parser.children), 1, parser.children)
        self.assertIn('card', parser.children[0][1].get('class', '').split())

    def test_anonymous_auth_pages_have_one_card(self):
        for name in ('login', 'register'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assert_single_card(response)
                self.assertContains(response, 'csrfmiddlewaretoken')

    def test_preferences_and_all_statuses_have_one_card(self):
        user = User.objects.create_user(username='layout-participant')
        self.client.force_login(user)
        response = self.client.get(reverse('account_preferences'))
        self.assert_single_card(response)
        self.assertContains(response, 'Save preferences')
        for status in ('pending', 'approved', 'rejected', 'suspended'):
            User.objects.filter(pk=user.pk).update(participant_status=status)
            with self.subTest(status=status):
                response = self.client.get(reverse('participant_status'))
                self.assert_single_card(response)
                self.assertEqual(response.context['status'], status)

    def test_invalid_forms_keep_card_and_errors(self):
        for name in ('login', 'register'):
            with self.subTest(page=name):
                response = self.client.post(reverse(name), {})
                self.assert_single_card(response)
                self.assertTrue(response.context['form'].errors)
        user = User.objects.create_user(username='invalid-preferences')
        self.client.force_login(user)
        response = self.client.post(reverse('account_preferences'), {'default_request_visibility': 'unknown', 'default_body_visibility': 'public'})
        self.assert_single_card(response)
        self.assertTrue(response.context['form'].errors)

    def test_hub_and_every_linked_destination_render(self):
        organizer = User.objects.create_superuser(username='layout-organizer', password='Layout-test-79!')
        self.client.force_login(organizer)
        response = self.client.get(reverse('admin_hub'))
        self.assert_single_card(response)
        links = [link for section in response.context['sections'] for link in section['links']]
        self.assertTrue(links)
        for link in links:
            with self.subTest(label=link['label'], url=link['url']):
                destination = self.client.get(link['url'], follow=True)
                self.assertEqual(destination.status_code, 200)
                self.assertNotContains(destination, 'Traceback (most recent call last)')

    def test_admin_model_add_pages_render(self):
        organizer = User.objects.create_superuser(username='add-layout-organizer', password='Layout-test-79!')
        self.client.force_login(organizer)
        for app, model in (('accounts', 'user'), ('accounts', 'registrationsource'), ('people', 'person'), ('people', 'place'), ('letters', 'letterconcept'), ('letters', 'letterinstance'), ('letters', 'stamp'), ('letters', 'stampupdate'), ('letters', 'letterhop'), ('topics', 'topic'), ('media_app', 'mediaitem')):
            with self.subTest(app=app, model=model):
                response = self.client.get(reverse(f'admin:{app}_{model}_add'))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'admin/change_form.html')
