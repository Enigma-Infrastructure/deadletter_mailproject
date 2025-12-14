# people/admin.py
from django.contrib import admin
from .models import Person


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = (
        "nickname",
        "social_place_name",
        "city",
        "region",
        "state",
        "created_at",
    )
    search_fields = (
        "nickname",
        "social_place_name",
        "city",
        "region",
        "state",
    )
    list_filter = (
        "city",
        "state",
        "region",
    )
