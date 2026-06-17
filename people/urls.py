from django.urls import path
from . import views

urlpatterns = [
    path("request/",        views.request_a_letter,    name="request_a_letter"),
    path("request/thanks/", views.request_letter_thanks, name="request_letter_thanks"),
]
