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


class GeneratedCharacter(models.Model):
    """Persists an Eclipse Phase 2E Point-Buy v2 (or future Life-Path) character sheet and optional Dossier link."""

    SOURCE_POINT_BUY_V2 = "point_buy_v2"
    SOURCE_LIFE_PATH = "life_path"
    SOURCE_SYSTEM_CHOICES = [
        (SOURCE_POINT_BUY_V2, "Point-Buy (v2)"),
        (SOURCE_LIFE_PATH, "Life-Path"),
    ]
    STATUS_DRAFT = "draft"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_COMPLETED, "Completed"),
    ]
    PROTECTION_NONE = "none"
    PROTECTION_SECRET = "secret"
    PROTECTION_ST_ONLY = "st_only"
    PROTECTION_CHOICES = [
        (PROTECTION_NONE, "None"),
        (PROTECTION_SECRET, "Secret"),
        (PROTECTION_ST_ONLY, "ST-Only"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="generated_characters",
    )
    dossier = models.ForeignKey(
        "CharacterDossier",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_characters",
    )
    external_id = models.CharField(max_length=64, blank=True, db_index=True)
    character_name = models.CharField(max_length=160)
    source_system = models.CharField(
        max_length=32,
        choices=SOURCE_SYSTEM_CHOICES,
        default=SOURCE_POINT_BUY_V2,
    )
    raw_data = models.JSONField(default=dict, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        help_text="Draft until the sheet is Finalized; completion is a soft, reviewable state.",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    public_view = models.BooleanField(
        default=False,
        help_text="Allow the completed sheet to be publicly Reviewed (with protected sections locked).",
    )
    protection = models.CharField(
        max_length=16,
        choices=PROTECTION_CHOICES,
        default=PROTECTION_NONE,
    )
    secret_puzzle_prompt = models.TextField(
        blank=True,
        help_text="Secret lock: the puzzle/prompt shown to viewers.",
    )
    secret_answer_hash = models.CharField(
        max_length=256, blank=True,
        help_text="Secret lock: hashed answer. Never exposed to clients.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "external_id"],
                condition=models.Q(external_id__gt=""),
                name="spacemarches_uniq_user_genchar_ext_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.character_name} ({self.user})"


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
    active_dossier = models.ForeignKey(
        "CharacterDossier",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_discord_links",
    )
    linked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.discord_user_id == "":
            self.discord_user_id = None
        if self.link_code == "":
            self.link_code = None
        super().save(*args, **kwargs)

    @property
    def active_or_latest_status(self) -> str:
        return self.discord_user_id or f"pending:{self.link_code}"

    def __str__(self) -> str:
        return f"{self.user} ({self.active_or_latest_status})"


class CharacterDossier(models.Model):
    """Narrativized Eclipse Phase / Spacemarches character questionnaire dossier."""

    VOICE_FIRST_PERSON = "FIRST_PERSON"
    VOICE_OMNISCIENT = "OMNISCIENT"
    NARRATIVE_VOICE_CHOICES = [
        (VOICE_FIRST_PERSON, "First-person agent log"),
        (VOICE_OMNISCIENT, "Omniscient institutional dossier"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="character_dossiers",
    )
    discord_owner_id = models.CharField(max_length=64, blank=True, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invited_character_dossiers",
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
    protection = models.CharField(
        max_length=16,
        choices=GeneratedCharacter.PROTECTION_CHOICES,
        default=GeneratedCharacter.PROTECTION_NONE,
        help_text="Whole-section protection: none / secret / ST-only.",
    )
    secret_puzzle_prompt = models.TextField(
        blank=True,
        help_text="Secret lock: the puzzle/prompt shown to viewers.",
    )
    secret_answer_hash = models.CharField(
        max_length=256, blank=True,
        help_text="Secret lock: hashed answer. Never exposed to clients.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("user", "slug"),)
        ordering = ["-updated_at"]

    @property
    def is_claimed(self) -> bool:
        return self.user_id is not None

    @property
    def owner_display(self) -> str:
        if self.user_id is not None:
            return str(self.user)
        if self.discord_owner_id:
            return f"Unclaimed (Discord:{self.discord_owner_id})"
        return "Unclaimed"

    def save(self, *args, **kwargs):
        if not self.slug and self.character_name:
            base = slugify(self.character_name)[:140] or "character"
            candidate = base
            counter = 1
            if self.user_id is not None:
                qs = CharacterDossier.objects.filter(user=self.user)
            elif self.discord_owner_id:
                qs = CharacterDossier.objects.filter(
                    user__isnull=True,
                    discord_owner_id=self.discord_owner_id,
                )
            else:
                qs = CharacterDossier.objects.filter(user__isnull=True)
            while qs.filter(slug=candidate).exclude(pk=self.pk).exists():
                counter += 1
                candidate = f"{base[:140]}-{counter}"
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.character_name} ({self.owner_display})"


class EclipsePhaseCensus(models.Model):
    """Guided Eclipse Phase setting walkthrough & character census (ShadowDragon8685 / GearheadLydia)."""

    PROTECTION_TARGET_KIND = "census"

    VOICE_FIRST_PERSON = "FIRST_PERSON"
    VOICE_OMNISCIENT = "OMNISCIENT"
    NARRATIVE_VOICE_CHOICES = [
        (VOICE_FIRST_PERSON, "First-person (as character)"),
        (VOICE_OMNISCIENT, "Omniscient narrative"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="eclipse_phase_censuses",
    )
    dossier = models.ForeignKey(
        "CharacterDossier",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="censuses",
    )
    character = models.ForeignKey(
        "GeneratedCharacter",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="censuses",
    )
    character_name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160)
    narrative_voice = models.CharField(
        max_length=20,
        choices=NARRATIVE_VOICE_CHOICES,
        default=VOICE_FIRST_PERSON,
    )
    responses = models.JSONField(default=dict, blank=True)
    show_sexuality_sections = models.BooleanField(
        default=True,
        help_text="Include optional sexuality and sexual-experience sections (13c, 13e).",
    )
    show_sensitive_appendix = models.BooleanField(
        default=False,
        help_text="Opt in to the Moved Questions appendix (13d1-13d6).",
    )
    public_view = models.BooleanField(
        default=False,
        help_text="Allow this Census to be publicly reviewed (respecting protection locks).",
    )
    protection = models.CharField(
        max_length=16,
        choices=GeneratedCharacter.PROTECTION_CHOICES,
        default=GeneratedCharacter.PROTECTION_NONE,
        help_text="Whole-section protection: none / secret / ST-only.",
    )
    secret_puzzle_prompt = models.TextField(
        blank=True,
        help_text="Secret lock: the puzzle/prompt shown to viewers.",
    )
    secret_answer_hash = models.CharField(
        max_length=256,
        blank=True,
        help_text="Secret lock: hashed answer. Never exposed to clients.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("user", "slug"),)
        ordering = ["-updated_at"]

    def save(self, *args, **kwargs):
        if not self.slug and self.character_name:
            base = slugify(self.character_name)[:140] or "census"
            candidate = base
            counter = 1
            qs = EclipsePhaseCensus.objects.filter(user=self.user)
            while qs.filter(slug=candidate).exclude(pk=self.pk).exists():
                counter += 1
                candidate = f"{base[:140]}-{counter}"
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.character_name} Census ({self.user})"


class ProtectionAccessLog(models.Model):
    """Append-only log of ST-only / secret view access (an Eclipse Phase-themed security log).

    Entries are created when an ST-only protected section is viewed and when a secret
    section is unlocked. The content owner can review the log when they come back.
    """

    TARGET_CHARACTER = "character"
    TARGET_DOSSIER = "dossier"
    TARGET_CENSUS = "census"
    TARGET_CHOICES = [
        (TARGET_CHARACTER, "Character Sheet"),
        (TARGET_DOSSIER, "Character Dossier"),
        (TARGET_CENSUS, "Eclipse Phase Census"),
    ]

    target_kind = models.CharField(max_length=16, choices=TARGET_CHOICES)
    target_pk = models.IntegerField()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="protection_access_log_entries",
    )
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="protection_accesses_by_viewer",
    )
    protection_type = models.CharField(max_length=16)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_target_kind_display()} #{self.target_pk} by {self.viewer} ({self.protection_type})"


class DiscordIntakeInvite(models.Model):
    """Authorizes an unlinked Discord user to create and edit character dossiers after ST/linked-user /intake."""

    discord_user_id = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sent_discord_intake_invites",
    )
    active_dossier = models.ForeignKey(
        CharacterDossier,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_intake_invites",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        inviter = str(self.invited_by) if self.invited_by_id else "Discord ST"
        return f"IntakeInvite(discord:{self.discord_user_id}, by={inviter})"


class DesignPack(models.Model):
    """Rulebook or custom content pack grouping Ep2Entry records for Compendium & MeshNet."""

    TIER_CRB = "crb"
    TIER_CRB_STORYTELLER = "crb_storyteller"
    TIER_COPT = "copt"
    TIER_SPACEMARCHES = "spacemarches"
    TIER_CUSTOM = "custom"
    TIER_CHOICES = [
        (TIER_CRB, "EP2e Core Rulebook"),
        (TIER_CRB_STORYTELLER, "EP2e CRB (Storyteller)"),
        (TIER_COPT, "EP2e Character Options"),
        (TIER_SPACEMARCHES, "Spacemarches Official"),
        (TIER_CUSTOM, "Custom Pack"),
    ]

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    tier = models.CharField(max_length=24, choices=TIER_CHOICES, default=TIER_CUSTOM)
    is_storyteller_only = models.BooleanField(default=False)
    is_official = models.BooleanField(default=False)
    is_public = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="design_packs",
    )
    source_url = models.URLField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_official", "tier", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class Ep2Entry(models.Model):
    """A seeded or custom Eclipse Phase 2e reference data entry (item, tech, morph, trait, …).

    Sourced from the Bubz43/ep2e Foundry packs (CC BY 4.0) or custom DesignPacks.
    One row per pack entry; the full pack ``system`` payload is preserved in the
    ``system`` JSONField so data is lossless even before dedicated typed fields exist.
    """

    CATEGORY_MORPH = "morph"
    CATEGORY_GEAR = "gear"
    CATEGORY_TRAIT = "trait"
    CATEGORY_SUBSTANCE = "substance"
    CATEGORY_SLEIGHT = "sleight"
    CATEGORY_CHARACTER = "character"
    CATEGORY_SPECIAL = "special"
    CATEGORY_MISC = "misc"
    CATEGORY_SKILL = "skill"
    CATEGORY_KNOW_SKILL = "know_skill"
    CATEGORY_EGO = "ego"
    CATEGORY_SKILL_PACK = "skill_pack"
    CATEGORY_REP = "rep"
    CATEGORY_MOVEMENT = "movement"
    CATEGORY_ENVIRONMENT = "environment"
    CATEGORY_MODIFIER = "modifier"
    CATEGORY_WEAPON_ACCESSORY = "weapon_accessory"
    CATEGORY_ABILITY = "ability"

    CATEGORY_CHOICES = [
        (CATEGORY_MORPH, "Morph"),
        (CATEGORY_GEAR, "Gear / Tech"),
        (CATEGORY_TRAIT, "Trait"),
        (CATEGORY_SUBSTANCE, "Substance"),
        (CATEGORY_SLEIGHT, "Sleight"),
        (CATEGORY_CHARACTER, "Character / Creature"),
        (CATEGORY_SPECIAL, "Special"),
        (CATEGORY_MISC, "Other"),
        (CATEGORY_SKILL, "Active Skill"),
        (CATEGORY_KNOW_SKILL, "Know Skill"),
        (CATEGORY_EGO, "Ego"),
        (CATEGORY_SKILL_PACK, "Skill Pack"),
        (CATEGORY_REP, "Rep"),
        (CATEGORY_MOVEMENT, "Movement"),
        (CATEGORY_ENVIRONMENT, "Environment"),
        (CATEGORY_MODIFIER, "Success-Test Modifier"),
        (CATEGORY_WEAPON_ACCESSORY, "Weapon Accessory"),
        (CATEGORY_ABILITY, "Ability"),
    ]

    design_pack = models.ForeignKey(
        DesignPack,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="entries",
    )
    source = models.CharField(max_length=64, default="bubz-ep2e")
    pack = models.CharField(max_length=64)
    entry_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    entry_type = models.CharField(max_length=64, blank=True, default="")
    category = models.CharField(max_length=16, choices=CATEGORY_CHOICES)
    description = models.TextField(blank=True, default="")
    reference = models.CharField(max_length=255, blank=True, default="")
    is_storyteller_only = models.BooleanField(default=False)
    is_custom = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="custom_ep2_entries",
    )
    system = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "pack", "name"]
        indexes = [
            models.Index(fields=["category"]),
            models.Index(fields=["pack"]),
            models.Index(fields=["name"]),
            models.Index(fields=["is_storyteller_only"], name="sm_ep2_st_idx"),
            models.Index(fields=["is_custom"], name="sm_ep2_custom_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.pack})"
