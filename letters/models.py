from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string

from people.models import Person


def generate_letter_code() -> str:
    return get_random_string(10)


class LetterConcept(models.Model):
    """The idea/subject of a letter that might have many physical instances."""

    # Name/topic facing
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    write_prompt = models.TextField(
        blank=True,
        help_text="Optional guidance or script; often same as person's write_about.",
    )

    # Social destination
    destination_social_place_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Bar, camp, venue, etc., where this should arrive.",
    )
    destination_city = models.CharField(max_length=255, blank=True)
    destination_region = models.CharField(max_length=255, blank=True)
    destination_state = models.CharField(max_length=255, blank=True)

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


class LetterInstance(models.Model):
    """A physical or specific copy of a concept with a unique ID/QR."""

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

    # Social location of the physical piece “now”
    current_city = models.CharField(max_length=255, blank=True)
    current_region = models.CharField(max_length=255, blank=True)
    current_state = models.CharField(max_length=255, blank=True)
    current_social_place_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="If the letter is left at a specific place (bar, camp, etc.).",
    )

    status = models.CharField(
        max_length=32,
        choices=[
            ("created", "Created"),
            ("waiting", "Waiting for carrier"),
            ("traveling", "Traveling"),
            ("left", "Left at location"),
            ("delivered", "Delivered"),
            ("archived", "Archived"),
        ],
        default="created",
    )

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

# letters/models.py - ADD this after LetterInstance
class LetterHop(models.Model):
    STATUS_CHOICES = [
        ('waiting', 'Waiting to be carried'),
        ('picked_up', 'Picked up'),
        ('in_transit', 'In transit'),
        ('left_at_location', 'Left at location'),
        ('delivered', 'Delivered'),
        ('archived', 'Archived'),
    ]
    letter = models.ForeignKey(LetterInstance, on_delete=models.CASCADE, related_name='hops')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    venue_hint = models.CharField(max_length=255, blank=True, help_text="Bar, event, camp, etc.")
    notes = models.TextField(blank=True)
    image = models.ImageField(upload_to='letter_hops/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    class Meta:
        ordering = ['-created_at']
