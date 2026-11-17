from django.conf import settings
from django.db import models
from django.utils.text import slugify


class AgentSaveSlot(models.Model):
    """Persists client-side mesh-net localStorage / engine state per user slot."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="spacemarches_save_slots",
    )
    slot_name = models.CharField(max_length=64, default="auto")
    raw_state = models.JSONField(default=dict, blank=True)
    clearance_summary = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("user", "slot_name"),)
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.user} [{self.slot_name}]"


class OperationSession(models.Model):
    """Server-authoritative multiplayer TRPG campaign session."""

    story_slug = models.SlugField(max_length=120)
    title = models.CharField(max_length=200, blank=True)
    game_master = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spacemarches_gm_sessions",
    )
    invite_code = models.CharField(max_length=32, unique=True)
    party_state = models.JSONField(default=dict, blank=True)
    is_public_declassified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title or f"{self.story_slug} ({self.invite_code})"


class FieldAgent(models.Model):
    """Links an authenticated player to an OperationSession campaign."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="spacemarches_field_agents",
    )
    campaign = models.ForeignKey(
        OperationSession,
        on_delete=models.CASCADE,
        related_name="field_agents",
    )
    callsign = models.CharField(max_length=80)
    clearance_level = models.CharField(max_length=40, default="LEVEL-1")
    sheet_data = models.JSONField(default=dict, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("user", "campaign"),)
        ordering = ["callsign"]

    def __str__(self) -> str:
        return f"{self.callsign} ({self.user})"


class ArchiveEntry(models.Model):
    """Public or classified containment/lore archive entry."""

    slug = models.SlugField(max_length=140, unique=True)
    title = models.CharField(max_length=255)
    classification_level = models.CharField(max_length=64, default="DECLASSIFIED")
    body = models.TextField()
    is_public = models.BooleanField(default=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spacemarches_archives",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Archive entries"

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            self.slug = slugify(self.title)[:140]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"[{self.classification_level}] {self.title}"


class ForumThread(models.Model):
    """Discussion thread optionally linked to a declassified archive entry."""

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=160, unique=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spacemarches_forum_threads",
    )
    related_archive = models.ForeignKey(
        ArchiveEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="forum_threads",
    )
    is_public = models.BooleanField(default=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            base = slugify(self.title)[:140] or "thread"
            candidate = base
            counter = 1
            while ForumThread.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                counter += 1
                candidate = f"{base[:140]}-{counter}"
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title


class ForumPost(models.Model):
    """Reply inside a ForumThread."""

    thread = models.ForeignKey(
        ForumThread,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="spacemarches_forum_posts",
    )
    is_public = models.BooleanField(default=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Reply on {self.thread} by {self.author or 'Unknown'}"


class DiscordLink(models.Model):
    """Maps a website user account to their Discord user ID via one-time link code."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="discord_link",
    )
    discord_user_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    link_code = models.CharField(max_length=32, unique=True, null=True, blank=True)
    linked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.discord_user_id == "":
            self.discord_user_id = None
        if self.link_code == "":
            self.link_code = None
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        status = self.discord_user_id or f"pending:{self.link_code}"
        return f"{self.user} ({status})"


class CharacterDossier(models.Model):
    """Narrativized Eclipse Phase / Spacemarches character questionnaire dossier."""

    VOICE_FIRST_PERSON = "FIRST_PERSON"
    VOICE_OMNISCIENT = "OMNISCIENT"
    NARRATIVE_VOICE_CHOICES = [
        (VOICE_FIRST_PERSON, "First-person agent log"),
        (VOICE_OMNISCIENT, "Omniscient Foundation dossier"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="character_dossiers",
    )
    character_name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160)
    narrative_voice = models.CharField(
        max_length=20,
        choices=NARRATIVE_VOICE_CHOICES,
        default=VOICE_FIRST_PERSON,
    )
    responses = models.JSONField(default=dict, blank=True)
    show_sensitive_appendix = models.BooleanField(default=False)
    private_keys = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("user", "slug"),)
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        if not self.slug and self.character_name:
            base = slugify(self.character_name)[:140] or "character"
            candidate = base
            counter = 1
            while CharacterDossier.objects.filter(user=self.user, slug=candidate).exclude(pk=self.pk).exists():
                counter += 1
                candidate = f"{base[:140]}-{counter}"
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.character_name} ({self.user})"
