from django.conf import settings
from django.db import models

from letters.models import LetterConcept


class Topic(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=255,
        blank=True,
        help_text="Optional icon name/URL for UI.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="topics_created",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LetterTopic(models.Model):
    """Canonical link between a concept and a topic."""

    letter_concept = models.ForeignKey(
        LetterConcept,
        on_delete=models.CASCADE,
        related_name="letter_topics",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="letter_topics",
    )

    # Aggregated crowd info (can be updated offline).
    vote_count = models.PositiveIntegerField(default=0)
    consensus_ratio = models.FloatField(
        default=0.0,
        help_text="0–1; rough consensus measure.",
    )

    class Meta:
        unique_together = ("letter_concept", "topic")


class LetterTopicVote(models.Model):
    """Individual votes; can support future crowd games."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="topic_votes",
    )
    letter_concept = models.ForeignKey(
        LetterConcept,
        on_delete=models.CASCADE,
        related_name="topic_votes",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="topic_votes",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "letter_concept", "topic")
