from django.urls import path
from . import views
from .privacy import public_letter_required

urlpatterns = [
    path("read/", views.letter_read_list, name="letter_read_list"),
    path("write/queue/", views.letter_write_queue, name="letter_write_queue"),
    path("write/claim/<int:pk>/", views.letter_write_claim, name="letter_write_claim"),
    path("write/confirm/<str:code>/", public_letter_required(views.letter_write_confirm), name="letter_write_confirm"),
    path("review/queue/", views.letter_review_queue, name="letter_review_queue"),
    path("print/queue/", views.print_queue, name="print_queue"),
    path("print/batch/", views.print_batch, name="print_batch"),
    path("print/confirm/", views.print_confirm, name="print_confirm"),
    path("print/<str:code>/", views.letter_print_view, name="letter_print"),
    path("l/<str:code>/", views.letter_public_page, name="letter_public"),
    path("carry/", views.carry_list, name="carry_list"),
    path("api/letters/", views.LettersInMyAreaAPIView.as_view(), name="letters_in_my_area_api"),
    path("desk/", views.write_read_home, name="write_read_home"),
    path("desk/read/", views.desk_read_list, name="desk_read_list"),
]
