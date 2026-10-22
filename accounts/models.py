# accounts/models.py
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for the project.

    PII (email, etc.) lives here or in related profile models,
    not in Person / letters.
    """
    is_collaborator = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.username


class ReputationNetwork(models.Model):
    """
    A reputation network: a scope in which reputation is earned and ranked.
    Supports multiple networks later (e.g. per-event, per-city, global).
    """

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ReputationEvent(models.Model):
    """
    Append-only ledger of courier engagement (reputation layer).

    Reputation is never stored as a running total on the user; the
    leaderboard is computed by aggregating this ledger. Anonymous
    scans earn no reputation (no user to credit).
    """

    REASON_CHOICES = [
        ("spotted", "Spotted a letter"),
        ("photo", "Added a photo"),
        ("picked_up", "Picked up a letter to carry"),
        ("left_at_place", "Left a letter at a place"),
        ("delivered", "Delivered a letter"),
        ("note", "Left a note"),
        ("organizer", "Organizer bonus"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reputation_events",
    )
    reputation = models.IntegerField(default=0)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    letter = models.ForeignKey(
        "letters.LetterInstance",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reputation_events",
    )
    network = models.ForeignKey(
        "accounts.ReputationNetwork",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
        help_text="The reputation network this event belongs to (optional; supports multiple networks later).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} +{self.reputation} ({self.get_reason_display()})"

    @classmethod
    def award(cls, *, user, reason: str, letter=None, network=None) -> "ReputationEvent | None":
        """Award default reputation for a reason; returns None for anonymous users."""
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        default_reputation = {
            "spotted": 5,
            "photo": 5,
            "picked_up": 10,
            "left_at_place": 15,
            "delivered": 25,
            "note": 2,
            "organizer": 0,
        }
        return cls.objects.create(
            user=user,
            reason=reason,
            reputation=default_reputation.get(reason, 0),
            letter=letter,
            network=network,
        )

    @classmethod
    def leaderboard(cls, limit: int = 20, network=None):
        qs = cls.objects.values("user__username")
        if network is not None:
            qs = qs.filter(network=network)
        return (
            qs.annotate(total=models.Sum("reputation"), contributions=models.Count("id"))
            .order_by("-total")[:limit]
        )
