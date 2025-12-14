from django.conf import settings
from django.db import models


class Person(models.Model):
    # Public, art-facing identity
    nickname = models.CharField(max_length=255)

    # Social geography (soft address)
    city = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=255, blank=True)

    # Social address: where to aim the letter
    social_place_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Bar, camp, venue, event space, etc.",
    )

    # Topic / “what to write about”
    write_about = models.TextField(
        blank=True,
        help_text="Short topic or prompt for this person.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="people_created",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.nickname or f"Person {self.pk}"
