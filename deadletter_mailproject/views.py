from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect

from letters.models import LetterInstance


def home(request):
    recent_letters = (
        LetterInstance.objects
        .filter(is_public=True, body_text__gt="")
        .select_related("request")
        .order_by("-created_at")[:6]
    )
    return render(request, "home.html", {"recent_letters": recent_letters})


@staff_member_required
def admin_hub(request):
    from letters.views import admin_hub as letters_admin_hub
    return letters_admin_hub(request)
