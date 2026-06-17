from django.urls import path
from . import views

urlpatterns = [
    # Reader
    path("read/",  views.letter_read_list, name="letter_read_list"),

    # Writer
    path("write/queue/",             views.letter_write_queue,   name="letter_write_queue"),
    path("write/claim/<int:pk>/",    views.letter_write_claim,   name="letter_write_claim"),
    path("write/confirm/<str:code>/",views.letter_write_confirm, name="letter_write_confirm"),

    # Print
    path("print/queue/",        views.print_queue,       name="print_queue"),
    path("print/batch/",        views.print_batch,       name="print_batch"),
    path("print/<str:code>/",   views.letter_print_view, name="letter_print"),

    # Public QR landing
    path("l/<str:code>/",       views.letter_public_page, name="letter_public"),

    # Carry / hops
    path("carry/",                              views.carry_list,        name="carry_list"),
    path("l/<str:code>/hop/",                   views.letter_hop_create, name="letter_hop_create"),
    path("batch/<str:batch_id>/confirm/",       views.letter_hop_create, name="batch_confirm"),

    # Legacy desk routes — all redirect harmlessly
    path("desk/",             views.write_read_home,   name="write_read_home"),
    path("desk/start/",       views.quick_write_start, name="quick_write_start"),
    path("desk/write/<int:pk>/", views.quick_write_letter, name="quick_write_letter"),
    path("desk/read/",        views.desk_read_list,    name="desk_read_list"),
]
