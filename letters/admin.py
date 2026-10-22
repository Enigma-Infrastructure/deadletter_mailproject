# letters/admin.py
from django.contrib import admin
from .models import LetterConcept, LetterInstance, LetterHop, Stamp, StampUpdate


@admin.register(LetterConcept)
class LetterConceptAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "created_for",
        "destination_place",
        "destination_city",
        "created_at",
    )
    search_fields = ("title", "description", "write_prompt")
    list_filter = ("destination_city",)


@admin.register(LetterInstance)
class LetterInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "concept",
        "recipient",
        "status",
        "origin",
        "needs_printing",
        "current_place",
        "current_city",
        "is_public",
        "created_at",
    )
    search_fields = ("code",)
    list_filter = (
        "status",
        "origin",
        "needs_printing",
        "current_city",
        "is_public",
    )


@admin.register(LetterHop)
class LetterHopAdmin(admin.ModelAdmin):
    list_display = ("letter", "status", "place", "city", "created_at", "updated_by")
    list_filter = ("status",)
    search_fields = ("letter__code",)


@admin.register(Stamp)
class StampAdmin(admin.ModelAdmin):
    list_display = ("number", "letter", "is_active", "issued_at", "issued_by")
    search_fields = ("number", "letter__code")
    list_filter = ("is_active",)


@admin.register(StampUpdate)
class StampUpdateAdmin(admin.ModelAdmin):
    list_display = (
        "stamp",
        "kind",
        "place",
        "instagram_handle",
        "media",
        "created_at",
    )
    list_filter = ("kind",)
    search_fields = ("stamp__number", "note", "instagram_handle")
