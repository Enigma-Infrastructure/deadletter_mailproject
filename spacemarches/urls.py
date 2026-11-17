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
    # Authenticated gameplay & cloud sync
    path("terminal/", views.terminal, name="terminal"),
    path("api/sync/", views.api_sync, name="api_sync"),
    # Authenticated character dossiers & Discord linking
    path("dossier/", views.dossier_list, name="dossier_list"),
    path("dossier/discord-link/", views.generate_discord_code, name="generate_discord_code"),
    path("dossier/<slug:slug>/", views.dossier_detail, name="dossier_detail"),
    path("dossier/<slug:slug>/answer/", views.dossier_answer, name="dossier_answer"),
    path("dossier/<slug:slug>/export/", views.dossier_export, name="dossier_export"),
    path("dossier/<slug:slug>/toggle-sensitive/", views.dossier_toggle_sensitive, name="dossier_toggle_sensitive"),
]
