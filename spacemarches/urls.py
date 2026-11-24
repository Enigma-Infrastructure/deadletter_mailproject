from django.urls import path

from . import views

app_name = "spacemarches"

urlpatterns = [
    # Public routes
    path("", views.portal, name="portal"),
    path("archives/", views.archive_list, name="archive_list"),
    path("archives/<slug:slug>/", views.archive_detail, name="archive_detail"),
    path("forums/", views.forum_list, name="forum_list"),
    path("forums/new/", views.forum_new, name="forum_new"),
    path("forums/<slug:slug>/", views.forum_detail, name="forum_detail"),
    path("forums/<slug:slug>/reply/", views.forum_reply, name="forum_reply"),
    # Public MeshNet / Point-Buy v2 character generator (anonymous export + optional cloud save CTA)
    path("meshnet/", views.generator, name="meshnet"),
    path("generator/", views.generator, name="generator"),
    # Legacy authenticated shell alias & cloud sync
    path("terminal/", views.terminal, name="terminal"),
    path("api/sync/", views.api_sync, name="api_sync"),
    path("characters/", views.character_roster, name="character_roster"),
    path("characters/<int:pk>/export/", views.character_export, name="character_export"),
    path("characters/<int:pk>/link/", views.character_link_dossier, name="character_link_dossier"),
    path("characters/<int:pk>/delete/", views.character_delete, name="character_delete"),
    path("api/characters/", views.api_characters, name="api_characters"),
    path("api/characters/<int:pk>/", views.api_character_detail, name="api_character_detail"),
    path("api/characters/<int:pk>/link-dossier/", views.api_character_link_dossier, name="api_character_link_dossier"),
    # Authenticated character dossiers & Discord linking
    path("dossier/", views.dossier_list, name="dossier_list"),
    path("dossier/discord-link/", views.generate_discord_code, name="generate_discord_code"),
    path("dossier/id/<int:pk>/", views.dossier_detail_by_id, name="dossier_detail_by_id"),
    path("dossier/id/<int:pk>/answer/", views.dossier_answer_by_id, name="dossier_answer_by_id"),
    path("dossier/id/<int:pk>/export/", views.dossier_export_by_id, name="dossier_export_by_id"),
    path(
        "dossier/id/<int:pk>/toggle-sensitive/",
        views.dossier_toggle_sensitive_by_id,
        name="dossier_toggle_sensitive_by_id",
    ),
    path("dossier/id/<int:pk>/reassign/", views.dossier_reassign_by_id, name="dossier_reassign_by_id"),
    path("dossier/<slug:slug>/", views.dossier_detail, name="dossier_detail"),
    path("dossier/<slug:slug>/answer/", views.dossier_answer, name="dossier_answer"),
    path("dossier/<slug:slug>/export/", views.dossier_export, name="dossier_export"),
    path("dossier/<slug:slug>/toggle-sensitive/", views.dossier_toggle_sensitive, name="dossier_toggle_sensitive"),
]
