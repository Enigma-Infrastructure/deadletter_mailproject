from django.contrib import admin
from django.urls import path, include
from .views import home, admin_hub

urlpatterns = [
    path("",          home,      name="home"),
    path("admin/hub/",admin_hub, name="admin_hub"),
    path("admin/",    admin.site.urls),

    path("accounts/", include("django.contrib.auth.urls")),

    path("write/",    include("people.urls")),
    path("letters/",  include("letters.urls")),
    path("media/",    include("media_app.urls")),

    # routing app (carry flow)
    path("carry/",    include("routing.urls")),
]
