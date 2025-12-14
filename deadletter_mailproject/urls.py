from django.contrib import admin
from django.urls import path, include
from .views import home, admin_hub

urlpatterns = [
    path("", home, name="home"),

    path("admin/hub/", admin_hub, name="admin_hub"),
    path("admin/", admin.site.urls),

    path("accounts/", include("django.contrib.auth.urls")),  # <- add this

    path("write/", include("people.urls")),
    path("carry/", include("routing.urls")),
    path("letters/", include("letters.urls")),
    path("topics/", include("topics.urls")),
    path("media/", include("media_app.urls")),
]
