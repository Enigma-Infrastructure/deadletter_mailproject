from django.urls import path
from . import views

urlpatterns = [
    # Reader view
    path("read/", views.letter_read_list, name="letter_read_list"),

    # Writer flows
    path("write/queue/", views.letter_write_queue, name="letter_write_queue"),
    path("write/claim/<int:pk>/", views.letter_write_claim, name="letter_write_claim"),
    path("write/confirm/<str:code>/", views.letter_write_confirm, name="letter_write_confirm"),

    # Print queue & batch (physical production pipeline)
    path("print/queue/", views.print_queue, name="print_queue"),
    path("print/batch/", views.print_batch, name="print_batch"),
    path("print/confirm/", views.print_confirm, name="print_confirm"),

    # Single print (must come AFTER queue/batch)
    path("print/<str:code>/", views.letter_print_view, name="letter_print"),

    # QR landing / public HTML
    path("l/<str:code>/", views.letter_public_page, name="letter_public"),

    # Carry / courier list
    path("carry/", views.carry_list, name="carry_list"),

    # JSON API (letters in play, place-based filter)
    path("api/letters/", views.LettersInMyAreaAPIView.as_view(), name="letters_in_my_area_api"),

    # Writing Desk (single-page submission)
    path("desk/", views.write_read_home, name="write_read_home"),
    path("desk/read/", views.desk_read_list, name="desk_read_list"),
]
