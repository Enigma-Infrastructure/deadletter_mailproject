from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


def home(request):
    return render(request, "base.html")

@staff_member_required
def admin_hub(request):
    # Central place to link to sub-areas
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
                {"label": "Write / Receive", "url": "/write/"},
                {"label": "Carry / Track", "url": "/carry/"},
            ],
        },
        {
            "title": "APIs",
            "links": [
                {"label": "Letters in my area (API)", "url": "/carry/api/letters/?city=&region=&state="},
            ],
        },
        {
            "title": "Domain admin",
            "links": [
                {"label": "People (recipients)", "url": "/admin/people/person/"},
                {"label": "Letter concepts", "url": "/admin/letters/letterconcept/"},
                {"label": "Letter instances", "url": "/admin/letters/letterinstance/"},
                {"label": "Letter events", "url": "/admin/letters/letterevent/"},
                {"label": "Topics", "url": "/admin/topics/topic/"},
                {"label": "Media items", "url": "/admin/media_app/mediaitem/"},
            ],
        },
    ]
    return render(request, "admin_hub.html", {"sections": sections})
