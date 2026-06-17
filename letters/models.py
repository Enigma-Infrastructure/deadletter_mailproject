from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string

from people.models import LetterRequest


def generate_letter_code() -> str:
    return get_random_string(10)


class LetterInstance(models.Model):
    """
    A written, physical letter tied to a specific LetterRequest.
    Each request can technically have multiple instances (e.g. a second
    attempt if the first is lost), but in practice it's one-to-one.
    """

    request = models.ForeignKey(
        LetterRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="instances",
        help_text="The letter request this was written in response to.",
    )

    code = models.CharField(
        max_length=32,
        unique=True,
        default=generate_letter_code,
        help_text="Short ID printed on the letter and encoded in QR code.",
    )

    body_text = models.TextField(
        blank=True,
        help_text="The written body of the letter.",
    )

    is_public = models.BooleanField(
        default=True,
        help_text="If false, hide from public reading views.",
    )

    written_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="letters_written",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        recipient = self.request.nickname if self.request else "Unknown"
        return f"{self.code} → {recipient}"


class LetterHop(models.Model):
    """
    One physical movement event for a letter.
    Each time a letter changes hands or location, a new hop is created.
    """

    STATUS_CHOICES = [
        ('waiting',          'Waiting to be carried'),
        ('picked_up',        'Picked up by carrier'),
        ('in_transit',       'In transit'),
        ('left_at_location', 'Left at location'),
        ('delivered',        'Delivered to recipient'),
        ('archived',         'Archived'),
    ]

    letter     = models.ForeignKey(LetterInstance, on_delete=models.CASCADE, related_name='hops')
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    city       = models.CharField(max_length=100, blank=True)
    region     = models.CharField(max_length=100, blank=True)
    venue_hint = models.CharField(max_length=255, blank=True, help_text="Bar, event, camp, etc.")
    notes      = models.TextField(blank=True)
    image      = models.ImageField(upload_to='letter_hops/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Hop [{self.status}] — {self.letter.code} @ {self.city or 'unknown'}"
