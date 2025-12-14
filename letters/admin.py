# letters/admin.py
from django.contrib import admin
from .models import LetterConcept, LetterInstance


@admin.register(LetterConcept)
class LetterConceptAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "created_for",
        "destination_social_place_name",
        "destination_city",
        "destination_region",
        "destination_state",
        "created_at",
    )
    search_fields = ("title", "description", "write_prompt")
    list_filter = ("destination_city", "destination_state")


@admin.register(LetterInstance)
class LetterInstanceAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "concept",
        "recipient",
        "status",
        "current_social_place_name",
        "current_city",
        "current_region",
        "current_state",
        "is_public",
        "created_at",
    )
    search_fields = ("code",)
    list_filter = ("status", "current_city", "current_state", "is_public")
