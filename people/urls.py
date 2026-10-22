from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    path("", RedirectView.as_view(url="/write/request/", permanent=False)),
    path("request/", views.request_a_letter, name="request_a_letter"),
    path("recipients/", views.recipient_list, name="recipient_list"),
]
