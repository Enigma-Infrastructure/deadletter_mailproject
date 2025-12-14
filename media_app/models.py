from django.conf import settings
from django.db import models
from letters.models import LetterInstance


class MediaItem(models.Model):
    KIND_CHOICES = [
        ("writer", "Writer"),
        ("carrier", "Carrier"),
        ("envelope_front", "Envelope front"),
        ("envelope_back", "Envelope back"),
        ("arrival", "Arrival"),
        ("other", "Other"),
    ]

    letter = models.ForeignKey(
        LetterInstance,
        on_delete=models.CASCADE,
        related_name="media_items",
    )

    file = models.ImageField(upload_to="letters/")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default="other")

    captured_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    caption = models.TextField(blank=True)
    hashtags = models.CharField(
        max_length=255,
        blank=True,
        help_text="Space or comma separated hashtags like '#piratemail #deadletter'.",
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="media_uploaded",
    )

    def __str__(self) -> str:
        return f"Media for {self.letter.code} ({self.kind})"
