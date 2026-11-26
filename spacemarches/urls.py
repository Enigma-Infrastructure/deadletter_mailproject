from django.urls import path

from . import views

app_name = "spacemarches"

urlpatterns = [
    # Public routes
    path("", views.portal, name="portal"),
    path("archives/", views.archive_list, name="archive_list"),
    path("archives/<slug:slug>/", views.archive_detail, name="archive_detail"),
    path("compendium/", views.compendium_list, name="compendium_list"),
    path("compendium/<str:entry_id>/", views.compendium_detail, name="compendium_detail"),
    path("packs/", views.design_pack_list, name="design_pack_list"),
    path("packs/<slug:slug>/", views.design_pack_detail, name="design_pack_detail"),
    path("packs/<slug:slug>/export/", views.design_pack_export, name="design_pack_export"),
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
    path("characters/<int:pk>/sync-profile/", views.character_sync_profile, name="character_sync_profile"),
    path("characters/<int:pk>/delete/", views.character_delete, name="character_delete"),
    path("characters/<int:pk>/complete/", views.character_complete, name="character_complete"),
    path("characters/<int:pk>/public/", views.character_public_toggle, name="character_public_toggle"),
    path("characters/<int:pk>/protection/", views.character_protection, name="character_protection"),
    path("api/ep2/", views.api_ep2_entries, name="api_ep2_data"),
    path("api/ep2/meta/", views.api_ep2_meta, name="api_ep2_meta"),
    path("api/ep2/<str:entry_id>/", views.api_ep2_entries, name="api_ep2_entry"),
    path("api/packs/", views.api_design_packs, name="api_design_packs"),
    path("api/packs/<slug:slug>/", views.api_design_pack_detail, name="api_design_pack_detail"),
    path("api/meshnet/packs/", views.api_meshnet_packs, name="api_meshnet_packs"),
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
    path("dossier/<slug:slug>/protection/", views.dossier_protection, name="dossier_protection"),
    path("dossier/<slug:slug>/review/", views.dossier_review, name="dossier_review"),
    path("dossier/id/<int:pk>/review/", views.dossier_review_by_id, name="dossier_review_by_id"),
    # Guided Eclipse Phase Census (community questionnaire walkthrough)
    path("census/", views.census_list, name="census_list"),
    path("census/<int:pk>/", views.census_detail, name="census_detail"),
    path("census/<int:pk>/answer/", views.census_answer, name="census_answer"),
    path("census/<int:pk>/settings/", views.census_settings, name="census_settings"),
    path("census/<int:pk>/protection/", views.census_protection, name="census_protection"),
    path("census/<int:pk>/export/", views.census_export, name="census_export"),
    path("census/<int:pk>/review/", views.census_review, name="census_review"),
    path("census/<int:pk>/delete/", views.census_delete, name="census_delete"),
]
