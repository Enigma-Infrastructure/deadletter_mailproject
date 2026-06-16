from django.urls import path
from . import views

urlpatterns = [
    path("", views.write_home, name="write_home"),
    path("thanks/<int:pk>/", views.write_thanks, name="write_thanks"),
    path("recipients/", views.recipient_list, name="recipient_list"),
    path("request/", views.request_a_letter, name="request_a_letter"),
    path("request/thanks/", views.request_letter_thanks, name="request_letter_thanks"),
]
