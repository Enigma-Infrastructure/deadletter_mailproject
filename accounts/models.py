# accounts/models.py
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for the project.
    """
    is_collaborator = models.BooleanField(default=False)

    def __str__(self) -> str:
        return self.username


class ParticipantProfile(models.Model):
    """
    Optional account-level profile.
    claimed_request links an account to a LetterRequest they submitted.
    Mk 1: entirely optional — no flow requires it.
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    claimed_request = models.ForeignKey(
        "people.LetterRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="profiles",
        help_text="The letter request this account is associated with, if any.",
    )

    # Optional PII, only for this account
    email_verified        = models.BooleanField(default=False)
    postal_address_line1  = models.CharField(max_length=255, blank=True)
    postal_city           = models.CharField(max_length=255, blank=True)
    postal_state          = models.CharField(max_length=255, blank=True)
    postal_postcode       = models.CharField(max_length=20,  blank=True)
    postal_country        = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Profile for {self.user}"
