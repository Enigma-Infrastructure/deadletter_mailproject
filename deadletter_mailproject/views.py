# deadletter_mailproject/views.py

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


def home(request):
    """Landing page: describes the project to a general audience."""
    return render(request, "deadletter_info.html")


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
                {"label": "Request a letter (intake)", "url": "/write/request/"},
                {"label": "Write & Read desk", "url": "/letters/desk/"},
                {"label": "Carry / Track", "url": "/letters/carry/"},
                {"label": "Scan a stamp", "url": "/scan/"},
                {"label": "Courier leaderboard", "url": "/leaderboard/"},
            ],
        },
        {
            "title": "Domain admin",
            "links": [
                {"label": "People (recipients)", "url": "/admin/people/person/"},
                {"label": "Pirate mail places", "url": "/admin/people/place/"},
                {"label": "Letter concepts", "url": "/admin/letters/letterconcept/"},
                {"label": "Letter instances", "url": "/admin/letters/letterinstance/"},
                {"label": "Stamps", "url": "/admin/letters/stamp/"},
                {"label": "Stamp updates", "url": "/admin/letters/stampupdate/"},
                {"label": "Letter hops", "url": "/admin/letters/letterhop/"},
                {"label": "Topics", "url": "/admin/topics/topic/"},
                {"label": "Media items", "url": "/admin/media_app/mediaitem/"},
            ],
        },
    ]
    return render(request, "admin_hub.html", {"sections": sections})
