# letters/admin.py
from django.contrib import admin
from .models import (
    DomainSubmissionReceipt,
    Letter,
    LetterConcept,
    LetterHop,
    LetterInstance,
    LetterRequest,
    Stamp,
    StampUpdate,
)


@admin.register(LetterRequest)
class LetterRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "recipient_alias",
        "destination_city",
        "requested_visibility",
        "is_published",
        "automatically_restricted",
        "is_open",
        "created_at",
    )
    list_filter = (
        "requested_visibility",
        "is_published",
        "automatically_restricted",
        "is_open",
        "destination_city",
    )
    search_fields = ("recipient_alias", "prompt", "destination_label")
    readonly_fields = ("legacy_source", "submitted_by", "owner", "created_at")
    raw_id_fields = ("recipient", "destination_place", "concept")


@admin.register(Letter)
class LetterAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "recipient_alias",
        "destination_city",
        "requested_visibility",
        "is_published",
        "automatically_restricted",
        "finalized_at",
        "created_at",
    )
    list_filter = (
        "requested_visibility",
        "is_published",
        "automatically_restricted",
        "destination_city",
    )
    search_fields = ("recipient_alias", "body_text", "prompt_snapshot", "destination_label")
    readonly_fields = ("writer", "finalized_at", "created_at")
    raw_id_fields = ("request", "concept", "recipient", "destination_place")


@admin.register(DomainSubmissionReceipt)
class DomainSubmissionReceiptAdmin(admin.ModelAdmin):
    list_display = ("id", "actor", "operation", "completed", "created_at")
    list_filter = ("operation", "completed")
    search_fields = ("actor__username", "key_digest", "payload_digest")
    readonly_fields = (
        "actor",
        "operation",
        "key_digest",
        "payload_digest",
        "completed",
        "request_result",
        "letter_result",
        "instance_result",
        "created_at",
    )


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
        "authored_letter",
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
    raw_id_fields = ("authored_letter", "concept", "recipient", "current_place")


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
