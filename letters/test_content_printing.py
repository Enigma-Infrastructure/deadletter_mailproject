from html.parser import HTMLParser
from io import BytesIO
from tempfile import TemporaryDirectory

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from media_app.models import MediaItem
from .forms import ScanUpdateForm
from .markdown_utils import render_markdown_safe
from .models import LetterHop, LetterInstance, Stamp, StampUpdate


def image_upload(size_padding=0):
    stream = BytesIO()
    Image.new("RGB", (2, 2), "white").save(stream, format="PNG")
    return SimpleUploadedFile(
        "test.png", stream.getvalue() + b"x" * size_padding,
        content_type="image/png",
    )


class UploadValidationTests(SimpleTestCase):
    def test_photo_is_optional(self):
        self.assertTrue(ScanUpdateForm({"kind": "spotted"}).is_valid())

    def test_valid_image_is_accepted(self):
        form = ScanUpdateForm({"kind": "photo_only"}, {"photo": image_upload()})
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_fake_image_is_rejected(self):
        upload = SimpleUploadedFile("fake.png", b"<script>alert(1)</script>", content_type="image/png")
        form = ScanUpdateForm({"kind": "photo_only"}, {"photo": upload})
        self.assertFalse(form.is_valid())
        self.assertIn("photo", form.errors)

    def test_oversized_image_is_rejected(self):
        form = ScanUpdateForm(
            {"kind": "photo_only"}, {"photo": image_upload(5 * 1024 * 1024)},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("photo", form.errors)

    def test_existing_size_boundary_and_content_type_policy(self):
        # Test the custom validator separately from Pillow's image verification.
        form = ScanUpdateForm()
        boundary = SimpleUploadedFile("boundary.png", b"x" * (5 * 1024 * 1024), content_type="image/png")
        form.cleaned_data = {"photo": boundary}
        self.assertIs(form.clean_photo(), boundary)
        unsupported = SimpleUploadedFile("image.bmp", b"x", content_type="image/bmp")
        form.cleaned_data = {"photo": unsupported}
        with self.assertRaises(ValidationError):
            form.clean_photo()


class ParsedHTML(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class MarkdownSafetyTests(SimpleTestCase):
    def test_normal_formatting_and_https_link_survive(self):
        html = render_markdown_safe("**Hello** and *friend* [visit](https://example.com)")
        self.assertIn("<strong>Hello</strong>", html)
        self.assertIn("<em>friend</em>", html)
        self.assertIn("https://example.com", html)

    def test_active_elements_and_event_attributes_are_removed(self):
        html = render_markdown_safe(
            '<script>alert(1)</script><iframe src="https://example.com"></iframe>'
            '<img src="x" onerror="alert(1)"><a href="https://example.com" onclick="alert(1)">link</a>'
        )
        for tag, attrs in ParsedHTML(html).elements:
            self.assertNotIn(tag, {"script", "iframe", "img", "object", "embed"})
            self.assertFalse(any(name.lower().startswith("on") for name in attrs))

    def test_unsafe_link_schemes_are_removed(self):
        for href in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "java&#x73;cript:alert(1)", "data:text/html,bad", "vbscript:bad"):
            with self.subTest(href=href):
                html = render_markdown_safe(f'<a href="{href}">link</a>')
                for tag, attrs in ParsedHTML(html).elements:
                    if "href" in attrs:
                        scheme = attrs["href"].strip().split(":", 1)[0].lower()
                        self.assertNotIn(scheme, {"javascript", "data", "vbscript"})

    def test_empty_content_is_safe(self):
        self.assertEqual(render_markdown_safe(""), "")


class UploadEndpointTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings_override = override_settings(MEDIA_ROOT=directory.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        cache.clear()
        self.addCleanup(cache.clear)
        self.letter = LetterInstance.objects.create(is_public=True)
        self.stamp = Stamp.objects.create(letter=self.letter)
        self.url = reverse("scan_stamp", kwargs={"number": self.stamp.number})

    def test_valid_photo_is_saved_and_linked(self):
        response = self.client.post(self.url, {"kind": "photo_only", "photo": image_upload()})
        self.assertEqual(response.status_code, 302)
        media = MediaItem.objects.get()
        self.assertEqual(media.letter, self.letter)
        self.assertEqual(StampUpdate.objects.get().media, media)
        self.assertTrue(media.file.storage.exists(media.file.name))
        self.assertFalse(LetterHop.objects.exists())

    def test_invalid_photo_creates_no_records_or_state_change(self):
        response = self.client.post(self.url, {
            "kind": "delivered",
            "photo": SimpleUploadedFile("fake.png", b"not an image", content_type="image/png"),
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("photo", response.context["form"].errors)
        self.assertFalse(MediaItem.objects.exists())
        self.assertFalse(StampUpdate.objects.exists())
        self.assertFalse(LetterHop.objects.exists())
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.status, "created")


class PrintWorkflowTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="print-staff", password="test-only-password", is_staff=True,
        )
        self.letter = LetterInstance.objects.create(
            is_public=True, status="waiting_print", needs_printing=True, body_text="Print me",
        )

    def test_nonstaff_cannot_use_print_workflows(self):
        ordinary = get_user_model().objects.create_user(username="ordinary", password="test-only-password")
        for user in (None, ordinary):
            self.client.logout()
            if user is not None:
                self.client.force_login(user)
            for route in ("print_queue", "print_batch", "print_confirm"):
                with self.subTest(user=user, route=route):
                    response = self.client.post(reverse(route), {"letters": [self.letter.pk]})
                    self.assertEqual(response.status_code, 302)
                    self.assertIn("/admin/login/", response.url)
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.status, "waiting_print")
        self.assertFalse(Stamp.objects.exists())

    def test_batch_preview_does_not_issue_stamps(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("print_batch"), {"letters": [self.letter.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([letter.pk for letter in response.context["batch"]], [self.letter.pk])
        self.letter.refresh_from_db()
        self.assertTrue(self.letter.needs_printing)
        self.assertIsNone(self.letter.printed_at)
        self.assertFalse(Stamp.objects.exists())

    def test_confirmation_and_sequential_repeat_are_idempotent(self):
        self.client.force_login(self.staff)
        url = reverse("print_confirm")
        payload = {"letters": [self.letter.pk]}
        self.assertRedirects(self.client.post(url, payload), reverse("print_queue"), fetch_redirect_response=False)
        self.letter.refresh_from_db()
        self.assertFalse(self.letter.needs_printing)
        self.assertEqual(self.letter.status, "waiting_carrier")
        self.assertIsNotNone(self.letter.printed_at)
        first_printed_at = self.letter.printed_at
        stamp = Stamp.objects.get(letter=self.letter, is_active=True)
        self.assertEqual(stamp.issued_by, self.staff)
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.letter.refresh_from_db()
        self.assertEqual(self.letter.printed_at, first_printed_at)
        self.assertEqual(Stamp.objects.filter(letter=self.letter).count(), 1)
        self.assertEqual(Stamp.objects.get(letter=self.letter).pk, stamp.pk)

    def test_get_confirmation_does_not_mutate_letter(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("print_confirm")).status_code, 302)
        self.letter.refresh_from_db()
        self.assertTrue(self.letter.needs_printing)
        self.assertEqual(self.letter.status, "waiting_print")
        self.assertFalse(Stamp.objects.exists())

    def test_existing_active_stamp_is_reused(self):
        self.client.force_login(self.staff)
        existing = Stamp.objects.create(letter=self.letter, issued_by=self.staff)
        response = self.client.post(reverse("print_confirm"), {"letters": [self.letter.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Stamp.objects.filter(letter=self.letter).count(), 1)
        self.assertEqual(Stamp.objects.get(letter=self.letter).pk, existing.pk)
