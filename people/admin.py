# people/admin.py
from django.contrib import admin
from .models import Person, Place


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "city", "is_active", "created_at")
    list_filter = ("kind", "city", "is_active")
    search_fields = ("name", "city", "description")


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("nickname", "pirate_place", "city", "email", "created_at")
    search_fields = ("nickname", "pirate_place__name", "city", "email")
    list_filter = ("city",)
