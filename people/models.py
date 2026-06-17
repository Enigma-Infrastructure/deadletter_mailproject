from django.conf import settings
from django.db import models


class LetterRequest(models.Model):
    """
    Someone who wants to receive a Pirate Mail letter.
    One row per request — no automatic deduplication.
    Two people named 'Wizard' with different addresses are two separate rows.
    """

    STATUS_CHOICES = [
        ('pending',    'Pending — waiting to be written'),
        ('written',    'Written — letter exists, not yet printed'),
        ('in_transit', 'In Transit — physically moving'),
        ('delivered',  'Delivered'),
        ('archived',   'Archived'),
    ]

    # Who wants the letter
    nickname       = models.CharField(max_length=255)
    pirate_address = models.CharField(
        max_length=255,
        blank=True,
        help_text="Social handle, venue, bar, camp, regular haunt — NOT a postal address.",
    )

    # Where they are
    city   = models.CharField(max_length=255, blank=True)
    state  = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=255, blank=True)

    # What to write about — this IS the letter prompt
    write_about = models.TextField(
        blank=True,
        help_text="What the writer should address. Becomes the prompt in the write queue.",
    )

    # Lifecycle
    status    = models.CharField(max_length=32, choices=STATUS_CHOICES, default='pending')
    is_active = models.BooleanField(default=True)

    # Private — organizer use only, never shown publicly
    email = models.EmailField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        location = ", ".join(filter(None, [self.city, self.state]))
        return f"{self.nickname}" + (f" ({location})" if location else "")
