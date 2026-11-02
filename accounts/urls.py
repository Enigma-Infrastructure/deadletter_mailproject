from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),
    path('status/', views.participant_status, name='participant_status'),
    path('preferences/', views.preferences, name='account_preferences'),
]
