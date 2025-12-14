from django.urls import path
from .views import LettersInMyAreaAPIView
from . import views

urlpatterns = [
    path("", views.carry_home, name="carry_home"),
    path("api/letters/", LettersInMyAreaAPIView.as_view(), name="letters_in_my_area_api"),
]
