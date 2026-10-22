from django.conf import settings
from django.db import models


class Place(models.Model):
    """
    A Pirate Mail Address: a social-network location where an individual
    can be found — a bar, bistro, Burning Man camp, volunteer group,
    nonprofit, cafe, bookstore, venue, art group, etc.

    This is NOT a postal address. Mail reaches a person by being handed
    to someone at this place who knows them.
    """

    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=32, blank=True)
    city = models.CharField(max_length=255, blank=True)

    description = models.TextField(
        blank=True,
        help_text="How a courier would actually find/hand off mail here.",
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="places_created",
    )

    class Meta:
        unique_together = ("name", "city")
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} — {self.city}" if self.city else self.name


class Person(models.Model):
    # Public, art-facing identity
    nickname = models.CharField(max_length=255)

    # Pirate mail address: the social place where this person can be found
    pirate_place = models.ForeignKey(
        Place,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="people",
        help_text="Social location (bar, camp, venue...) where mail can reach this person.",
    )
    city = models.CharField(max_length=255, blank=True)

    # Topic / "what to write about"
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

    email = models.EmailField(blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["nickname", "pirate_place"],
                name="unique_nickname_pirate_place",
            ),
        ]

    def __str__(self) -> str:
        return self.nickname or f"Person {self.pk}"

    @property
    def pirate_address_display(self) -> str:
        """Human-readable pirate mail address for envelopes and public pages."""
        place = self.pirate_place.name if self.pirate_place else ""
        city = self.pirate_place.city if self.pirate_place else self.city
        return (place or "").strip() + (f" · {city}" if city else "")
