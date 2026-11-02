from django.urls import path
from . import contact, views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('status/', views.participant_status, name='participant_status'),
    path('preferences/', views.preferences, name='account_preferences'),
    path('contact/', contact.contact, name='account_contact'),
    path('password_reset/', contact.recovery_unavailable, name='password_reset'),
    path('password_reset/done/', contact.recovery_unavailable, name='password_reset_done'),
    path('reset/done/', contact.recovery_unavailable, name='password_reset_complete'),
    path('reset/<uidb64>/<token>/', contact.recovery_unavailable, name='password_reset_confirm'),
]
