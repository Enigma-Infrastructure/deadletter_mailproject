# accounts/models.py
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from .email_state import EmailStateMixin


VISIBILITY_CHOICES = [("public", "Public"), ("participants_only", "Participants only")]
PARTICIPANT_STATUS_CHOICES = [
    ("pending", "Pending"), ("approved", "Approved"),
    ("rejected", "Rejected"), ("suspended", "Suspended"),
]


class RegistrationSource(models.Model):
    """Public event attribution, never an approval or authentication secret."""
    code = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.label

    def is_available(self, at=None):
        from django.utils import timezone
        at = timezone.now() if at is None else at
        return self.is_active and (self.expires_at is None or self.expires_at > at)


class User(EmailStateMixin, AbstractUser):
    """Account identity, participation approval, and future-submission defaults.

    Approval is independent of is_active, is_staff, and is_superuser.
    Email verification is separate from approval, identity, and ownership.
    """
    is_collaborator = models.BooleanField(default=False)
    participant_status = models.CharField(
        max_length=16, choices=PARTICIPANT_STATUS_CHOICES, default="pending",
    )
    default_request_visibility = models.CharField(
        max_length=24, choices=VISIBILITY_CHOICES, default="public",
    )
    default_body_visibility = models.CharField(
        max_length=24, choices=VISIBILITY_CHOICES, default="public",
    )
    registration_source = models.ForeignKey(
        RegistrationSource, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="registrations",
    )
    participant_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="participant_reviews",
    )
    participant_reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.username


class ReputationNetwork(models.Model):
    """A reputation network: an optional scope for reputation earned."""
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ReputationEvent(models.Model):
    """Append-only engagement ledger; anonymous scans earn no reputation."""
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
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reputation_events",
    )
    reputation = models.IntegerField(default=0)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    letter = models.ForeignKey(
        "letters.LetterInstance", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reputation_events",
    )
    network = models.ForeignKey(
        "accounts.ReputationNetwork", null=True, blank=True, on_delete=models.SET_NULL,
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
        if user is None or not getattr(user, "is_authenticated", False):
            return None
        default_reputation = {
            "spotted": 5, "photo": 5, "picked_up": 10, "left_at_place": 15,
            "delivered": 25, "note": 2, "organizer": 0,
        }
        return cls.objects.create(
            user=user, reason=reason, reputation=default_reputation.get(reason, 0),
            letter=letter, network=network,
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
