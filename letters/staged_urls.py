"""Isolated URL configuration for staged HTTP integration tests only.

This URLconf is NOT included in the main project routing. It is used only
by the test module to exercise the staged HTTP adapters.
"""
from django.urls import path

from . import staged_http

urlpatterns = [
    # Audience list/detail (GET only)
    path("staged/requests/", staged_http.staged_request_list, name="staged_request_list"),
    path("staged/requests/<int:request_id>/", staged_http.staged_request_detail, name="staged_request_detail"),
    path("staged/letters/", staged_http.staged_letter_list, name="staged_letter_list"),
    path("staged/letters/<int:letter_id>/", staged_http.staged_letter_detail, name="staged_letter_detail"),

    # Private draft snapshot (GET only, approved owner/writer)
    path("staged/requests/<int:request_id>/draft/", staged_http.staged_request_draft_snapshot, name="staged_request_draft_snapshot"),
    path("staged/letters/<int:letter_id>/draft/", staged_http.staged_letter_draft_snapshot, name="staged_letter_draft_snapshot"),

    # Token-checked draft saves (POST only, CSRF protected)
    path("staged/requests/<int:request_id>/save/", staged_http.staged_request_draft_save, name="staged_request_draft_save"),
    path("staged/letters/<int:letter_id>/save/", staged_http.staged_letter_draft_save, name="staged_letter_draft_save"),

    # Creation with durable replay (POST only, CSRF protected)
    path("staged/requests/create/", staged_http.staged_request_create, name="staged_request_create"),
    path("staged/responses/create/", staged_http.staged_response_create, name="staged_response_create"),

    # Content review and publication (POST only, staff only)
    path("staged/requests/<int:request_id>/publish/", staged_http.staged_request_publish, name="staged_request_publish"),
    path("staged/letters/<int:letter_id>/publish/", staged_http.staged_letter_publish, name="staged_letter_publish"),
    path("staged/review/restrict/", staged_http.staged_content_restrict, name="staged_content_restrict"),
]
