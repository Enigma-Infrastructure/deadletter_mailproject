from django.contrib import admin
from .models import MediaItem


@admin.register(MediaItem)
class MediaItemAdmin(admin.ModelAdmin):
    list_display = ("letter", "kind", "uploaded_at", "uploaded_by")
    list_filter = ("kind",)
