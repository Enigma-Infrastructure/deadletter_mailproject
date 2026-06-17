from django.shortcuts import render, redirect
from .models import LetterRequest


def request_a_letter(request):
    """
    Public intake form — no login required.
    Anyone can submit themselves to receive a Pirate Mail letter.
    Each submission creates a fresh LetterRequest row (no deduplication).
    """
    if request.method == "POST":
        nickname       = (request.POST.get("nickname")       or "").strip() or "A Stranger"
        pirate_address = (request.POST.get("pirate_address") or "").strip()
        city           = (request.POST.get("city")           or "").strip()
        state          = (request.POST.get("state")          or "").strip()
        region         = (request.POST.get("region")         or "").strip()
        write_about    = (request.POST.get("write_about")    or "").strip()
        email          = (request.POST.get("email")          or "").strip()

        LetterRequest.objects.create(
            nickname=nickname,
            pirate_address=pirate_address,
            city=city,
            state=state,
            region=region,
            write_about=write_about,
            email=email,
            status="pending",
        )
        return redirect("request_letter_thanks")

    return render(request, "people/request_a_letter.html")


def request_letter_thanks(request):
    return render(request, "people/request_thanks.html")
