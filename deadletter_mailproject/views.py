# deadletter_mailproject/views.py

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


def home(request):
    return render(request, "base.html")


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

def desk_read_list(request):
    """
    Desk-only reading view: show recent public letters
    using the cyberpunk desk skin.
    """
    letters = (
        LetterInstance.objects.filter(is_public=True, body_text__gt="")
        .select_related("concept", "recipient")
        .order_by("-created_at")[:50]
    )
    return render(request, "cyberpunk/desk_read_list.html", {"letters": letters})
