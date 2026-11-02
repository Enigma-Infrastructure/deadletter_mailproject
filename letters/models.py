from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string

from people.models import Person, Place


def generate_letter_code() -> str:
    return get_random_string(10)


def generate_stamp_number() -> str:
    """Short, human-typeable stamp identifier (digits + unambiguous letters)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return get_random_string(8, allowed_chars=alphabet)


class LetterConcept(models.Model):
    """Legacy mixed-purpose concept/request record; retained during refactor."""

    # Name/topic facing
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    write_prompt = models.TextField(
        blank=True,
        help_text="Optional guidance or script; often same as person's write_about.",
    )

    # Pirate mail destination (social-network layer, not a postal address)
    destination_place = models.ForeignKey(
        Place,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="letter_concepts",
        help_text="Pirate mail address: social place where this letter should arrive.",
    )
    destination_city = models.CharField(max_length=255, blank=True)

    created_for = models.ForeignKey(
        Person,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="letter_concepts",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="letter_concepts_created",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title or f"LetterConcept {self.pk}"

    @property
    def destination_display(self) -> str:
        place = self.destination_place.name if self.destination_place else ""
        city = (
            self.destination_place.city
            if self.destination_place
            else self.destination_city
        )
        return (place or "").strip() + (f" · {city}" if city else "")


class LetterInstance(models.Model):
    """Physical copy; legacy content fields remain until workflow cutover."""

    ORIGIN_CHOICES = [
        ("desk", "Writing desk / iPad at an event"),
        ("online", "Online submission"),
        ("admin", "Admin / organizer"),
    ]

    STATUS_CHOICES = [
        ("created", "Created (digital only)"),
        ("waiting_print", "Waiting for print"),
        ("waiting_stamp", "Waiting for stamp"),
        ("waiting_carrier", "Waiting for carrier"),
        ("traveling", "Traveling"),
        ("left", "Left at location"),
        ("delivered", "Delivered"),
        ("archived", "Archived"),
    ]

    authored_letter = models.ForeignKey(
        'letters.Letter', null=True, blank=True, on_delete=models.PROTECT,
        related_name='instances', editable=False,
    )
    concept = models.ForeignKey(
        LetterConcept,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="instances",
    )
    recipient = models.ForeignKey(
        Person,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="letter_instances",
    )

    code = models.CharField(
        max_length=32,
        unique=True,
        default=generate_letter_code,
        help_text="Short ID printed on the letter and encoded in QR.",
    )

    # Letter content (digital)
    body_text = models.TextField(
        blank=True,
        help_text="Digital text of this specific letter, if written online.",
    )

    # Where the physical piece is "now" (pirate mail address / social place)
    current_place = models.ForeignKey(
        Place,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="letters_here",
        help_text="Social place the letter is currently at or heading toward.",
    )
    current_city = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default="created",
    )

    # Physical production pipeline (digital -> physical)
    origin = models.CharField(
        max_length=16,
        choices=ORIGIN_CHOICES,
        default="desk",
        help_text="Where this letter was created.",
    )
    needs_printing = models.BooleanField(
        default=True,
        help_text="True while this letter exists only digitally and must be printed/enveloped.",
    )
    printed_at = models.DateTimeField(null=True, blank=True)

    # Public readability control (for edge cases)
    is_public = models.BooleanField(
        default=True,
        help_text="If false, hide this letter body from public reading views.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="letter_instances_created",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} ({self.status})"

    @property
    def current_location_display(self) -> str:
        place = self.current_place.name if self.current_place else ""
        city = self.current_place.city if self.current_place else self.current_city
        return (place or "").strip() + (f" · {city}" if city else "")


class LetterHop(models.Model):
    """
    Chain-of-custody log: one row per physical handoff/move of a letter.
    Created by couriers (authenticated) or anonymous stamp scans.
    """

    STATUS_CHOICES = [
        ("waiting", "Waiting to be carried"),
        ("picked_up", "Picked up"),
        ("in_transit", "In transit"),
        ("left_at_location", "Left at location"),
        ("delivered", "Delivered"),
        ("archived", "Archived"),
    ]
    letter = models.ForeignKey(
        LetterInstance, on_delete=models.CASCADE, related_name="hops"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="waiting")
    place = models.ForeignKey(
        Place,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hops",
        help_text="Social place where this hop happened.",
    )
    city = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    image = models.ImageField(upload_to="letter_hops/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hops_logged",
    )

    class Meta:
        ordering = ["-created_at"]


class Stamp(models.Model):
    """
    A physical stamp affixed to a letter. Each stamp carries a unique
    number; a general QR code on the stamp leads to the scan landing
    page where the number is entered (or pre-filled from the QR URL).
    """

    letter = models.ForeignKey(
        LetterInstance,
        on_delete=models.CASCADE,
        related_name="stamps",
    )
    number = models.CharField(
        max_length=16,
        unique=True,
        default=generate_stamp_number,
        help_text="Unique identifier printed on the physical stamp.",
    )
    is_active = models.BooleanField(default=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stamps_issued",
    )

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self) -> str:
        return f"Stamp {self.number} on {self.letter.code}"


class StampUpdate(models.Model):
    """
    A reactive update posted by anyone who scanned a stamp: status change,
    note, photo, and/or Instagram tag. Movement kinds also create a
    LetterHop so the courier chain stays in one place.
    """

    KIND_CHOICES = [
        ("spotted", "Spotted it"),
        ("picked_up", "Picked it up to carry"),
        ("left_at_place", "Left it at a place"),
        ("delivered", "Delivered"),
        ("photo_only", "Just adding a photo / tag"),
    ]

    stamp = models.ForeignKey(
        Stamp,
        on_delete=models.CASCADE,
        related_name="updates",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="spotted")
    note = models.TextField(blank=True)
    place = models.ForeignKey(
        Place,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stamp_updates",
        help_text="Social place where this update happened (optional).",
    )

    instagram_handle = models.CharField(max_length=100, blank=True)
    media = models.ForeignKey(
        "media_app.MediaItem",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stamp_updates",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="stamp_updates_submitted",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} on {self.stamp.number}"


AUDIENCE_CHOICES = [('public', 'Public'), ('participants_only', 'Participants only')]


class LetterRequest(models.Model):
    """One recipient-specific invitation; not a reusable concept."""
    prompt = models.TextField(blank=True)
    recipient = models.ForeignKey('people.Person', null=True, blank=True, on_delete=models.SET_NULL, related_name='letter_requests')
    recipient_alias = models.CharField(max_length=255, blank=True)
    destination_place = models.ForeignKey('people.Place', null=True, blank=True, on_delete=models.SET_NULL, related_name='letter_requests')
    destination_city = models.CharField(max_length=255, blank=True)
    destination_label = models.CharField(max_length=1024, blank=True)
    concept = models.ForeignKey('letters.LetterConcept', null=True, blank=True, on_delete=models.SET_NULL, related_name='linked_requests')
    legacy_source = models.OneToOneField('letters.LetterConcept', null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name='migrated_request')
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name='letter_requests_submitted')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name='letter_requests_owned')
    requested_visibility = models.CharField(max_length=24, choices=AUDIENCE_CHOICES, default='participants_only')
    automatically_restricted = models.BooleanField(default=False, editable=False)
    restriction_reason = models.CharField(max_length=255, blank=True, editable=False)
    is_published = models.BooleanField(default=False, editable=False)
    is_open = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=models.Q(requested_visibility__in=['public', 'participants_only']), name='letter_req_visibility_valid')]

    def __str__(self):
        return f'Request {self.pk}'


class Letter(models.Model):
    """An authored work; its physical copies are LetterInstance rows."""
    request = models.ForeignKey('letters.LetterRequest', null=True, blank=True, on_delete=models.PROTECT, related_name='responses')
    concept = models.ForeignKey('letters.LetterConcept', null=True, blank=True, on_delete=models.SET_NULL, related_name='authored_letters')
    writer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name='letters_written')
    body_text = models.TextField(blank=True)
    prompt_snapshot = models.TextField(blank=True)
    recipient = models.ForeignKey('people.Person', null=True, blank=True, on_delete=models.SET_NULL, related_name='authored_letters')
    recipient_alias = models.CharField(max_length=255, blank=True)
    destination_place = models.ForeignKey('people.Place', null=True, blank=True, on_delete=models.SET_NULL, related_name='authored_letters')
    destination_city = models.CharField(max_length=255, blank=True)
    destination_label = models.CharField(max_length=1024, blank=True)
    requested_visibility = models.CharField(max_length=24, choices=AUDIENCE_CHOICES, default='participants_only')
    automatically_restricted = models.BooleanField(default=False, editable=False)
    restriction_reason = models.CharField(max_length=255, blank=True, editable=False)
    is_published = models.BooleanField(default=False, editable=False)
    finalized_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=models.Q(requested_visibility__in=['public', 'participants_only']), name='auth_letter_visibility_valid')]

    def __str__(self):
        return f'Letter {self.pk}'
