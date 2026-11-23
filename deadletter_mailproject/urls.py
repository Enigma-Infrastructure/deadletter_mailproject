from django.contrib import admin
from django.urls import path, include
from oauth2_provider.urls import app_name as oauth2_app_name, base_urlpatterns as oauth2_base_urlpatterns
from accounts import views as accounts_views
from letters import views as letters_views
from letters.privacy import public_stamp_required
from .views import home, admin_hub

urlpatterns = [
    path('', home, name='home'),
    path('admin/hub/', admin_hub, name='admin_hub'),
    path('admin/', admin.site.urls),
    path('o/', include((oauth2_base_urlpatterns, oauth2_app_name), namespace='oauth2_provider')),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('leaderboard/', accounts_views.leaderboard, name='leaderboard'),
    path('scan/', letters_views.scan_home, name='scan_home'),
    path('scan/<str:number>/', public_stamp_required(letters_views.scan_stamp), name='scan_stamp'),
    path('write/', include('people.urls')),
    path('letters/', include('letters.urls')),
    path('spacemarches/', include('spacemarches.urls')),
]


