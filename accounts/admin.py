from django.contrib import admin

from .models import ReputationEvent, ReputationNetwork


@admin.register(ReputationNetwork)
class ReputationNetworkAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at")
    search_fields = ("name", "description")


@admin.register(ReputationEvent)
class ReputationEventAdmin(admin.ModelAdmin):
    list_display = ("user", "reason", "reputation", "letter", "network", "created_at")
    list_filter = ("reason", "network")
    search_fields = ("user__username", "letter__code")
