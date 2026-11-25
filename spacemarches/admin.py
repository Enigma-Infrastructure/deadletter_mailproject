from django.contrib import admin

from .models import (
    AgentSaveSlot,
    ArchiveEntry,
    CharacterDossier,
    DesignPack,
    DiscordIntakeInvite,
    DiscordLink,
    Ep2Entry,
    FieldAgent,
    ForumPost,
    ForumThread,
    GeneratedCharacter,
    OperationSession,
)


@admin.register(AgentSaveSlot)
class AgentSaveSlotAdmin(admin.ModelAdmin):
    list_display = ("user", "slot_name", "updated_at")
    search_fields = ("user__username", "slot_name")


@admin.register(GeneratedCharacter)
class GeneratedCharacterAdmin(admin.ModelAdmin):
    list_display = ("character_name", "user", "dossier", "source_system", "external_id", "updated_at")
    list_filter = ("source_system",)
    search_fields = ("character_name", "external_id", "user__username", "dossier__character_name")


@admin.register(OperationSession)
class OperationSessionAdmin(admin.ModelAdmin):
    list_display = ("story_slug", "title", "invite_code", "game_master", "is_public_declassified", "created_at")
    list_filter = ("is_public_declassified",)
    search_fields = ("story_slug", "title", "invite_code")


@admin.register(FieldAgent)
class FieldAgentAdmin(admin.ModelAdmin):
    list_display = ("callsign", "user", "campaign", "clearance_level", "joined_at")
    list_filter = ("clearance_level",)
    search_fields = ("callsign", "user__username")


@admin.register(ArchiveEntry)
class ArchiveEntryAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "classification_level", "is_public", "author", "created_at")
    list_filter = ("is_public", "classification_level")
    search_fields = ("title", "slug", "body")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ForumThread)
class ForumThreadAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "author", "related_archive", "is_public", "created_at")
    list_filter = ("is_public",)
    search_fields = ("title", "slug", "body")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(ForumPost)
class ForumPostAdmin(admin.ModelAdmin):
    list_display = ("thread", "author", "is_public", "created_at")
    list_filter = ("is_public",)
    search_fields = ("body", "thread__title")


@admin.register(DiscordLink)
class DiscordLinkAdmin(admin.ModelAdmin):
    list_display = ("user", "discord_user_id", "active_dossier", "link_code", "linked_at")
    search_fields = ("user__username", "discord_user_id", "link_code", "active_dossier__character_name")


@admin.register(DiscordIntakeInvite)
class DiscordIntakeInviteAdmin(admin.ModelAdmin):
    list_display = ("discord_user_id", "invited_by", "active_dossier", "updated_at")
    search_fields = ("discord_user_id", "invited_by__username", "active_dossier__character_name")


@admin.register(CharacterDossier)
class CharacterDossierAdmin(admin.ModelAdmin):
    list_display = (
        "character_name",
        "user",
        "discord_owner_id",
        "invited_by",
        "narrative_voice",
        "show_sensitive_appendix",
        "updated_at",
    )
    list_filter = ("narrative_voice", "show_sensitive_appendix")
    search_fields = ("character_name", "slug", "user__username", "discord_owner_id")


@admin.register(DesignPack)
class DesignPackAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "tier", "is_official", "is_storyteller_only", "is_public", "is_active", "owner", "updated_at")
    list_filter = ("tier", "is_official", "is_storyteller_only", "is_public", "is_active")
    search_fields = ("name", "slug", "description", "owner__username")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Ep2Entry)
class Ep2EntryAdmin(admin.ModelAdmin):
    list_display = ("name", "design_pack", "pack", "category", "is_storyteller_only", "is_custom", "reference")
    list_filter = ("design_pack", "category", "is_storyteller_only", "is_custom", "pack")
    search_fields = ("name", "description", "reference", "entry_id")
    readonly_fields = ("entry_id", "source", "system")
    date_hierarchy = "updated_at"
