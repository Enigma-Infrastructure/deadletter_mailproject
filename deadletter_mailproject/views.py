# deadletter_mailproject/views.py

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from letters.models import LetterInstance


def home(request):
    recent_letters = (
        LetterInstance.objects
        .filter(is_public=True, body_text__gt="")
        .select_related("concept", "recipient")
        .order_by("-created_at")[:6]
    )
    return render(request, "home.html", {"recent_letters": recent_letters})


@staff_member_required
def admin_hub(request):
    sections = [
        {
            "title": "Django Admin",
            "links": [
                {"label": "Site admin", "url": "/admin/"},
            ],
        },
        {
            "title": "Public entry points",
            "links": [
                {"label": "Read Letters", "url": "/letters/read/"},
                {"label": "Get a Letter", "url": "/write/request/"},
                {"label": "Write & Read desk", "url": "/letters/desk/"},
                {"label": "Carry / Track", "url": "/letters/carry/"},
            ],
        },
        {
            "title": "Domain admin",
            "links": [
                {"label": "People (recipients)", "url": "/admin/people/person/"},
                {"label": "Letter concepts", "url": "/admin/letters/letterconcept/"},
                {"label": "Letter instances", "url": "/admin/letters/letterinstance/"},
                {"label": "Letter hops", "url": "/admin/letters/letterhop/"},
                {"label": "Topics", "url": "/admin/topics/topic/"},
                {"label": "Media items", "url": "/admin/media_app/mediaitem/"},
            ],
        },
    ]
    return render(request, "admin_hub.html", {"sections": sections})
