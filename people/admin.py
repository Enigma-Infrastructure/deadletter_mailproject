from django.contrib import admin
from .models import LetterRequest


@admin.register(LetterRequest)
class LetterRequestAdmin(admin.ModelAdmin):
    list_display  = (
        "nickname", "pirate_address", "city", "state",
        "region", "status", "is_active", "created_at",
    )
    list_filter   = ("status", "is_active", "city", "state")
    search_fields = ("nickname", "pirate_address", "city", "write_about")
    readonly_fields = ("created_at",)
    fieldsets = (
        ("Identity", {
            "fields": ("nickname", "pirate_address"),
        }),
        ("Location", {
            "fields": ("city", "state", "region"),
        }),
        ("Prompt", {
            "fields": ("write_about",),
        }),
        ("Status", {
            "fields": ("status", "is_active"),
        }),
        ("Private / Organizer", {
            "fields": ("email",),
            "classes": ("collapse",),
        }),
        ("Meta", {
            "fields": ("created_at",),
            "classes": ("collapse",),
        }),
    )
