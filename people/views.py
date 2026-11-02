from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.shortcuts import render

from letters.models import LetterConcept
from .forms import RequestALetterForm
from .models import Person, Place


def is_collaborator(user):
    return user.is_authenticated and getattr(user, "is_collaborator", False)


@user_passes_test(is_collaborator)
def recipient_list(request):
    people = Person.objects.select_related("pirate_place").order_by("-created_at")[:200]
    return render(request, "recipient_list.html", {"people": people})


def request_a_letter(request):
    """Public intake creates requests, never edits an existing recipient profile."""
    if request.method == "POST":
        form = RequestALetterForm(request.POST)
        if form.is_valid():
            nickname = form.cleaned_data["nickname"].strip() or "A Stranger"
            pirate_addr = form.cleaned_data["pirate_address"].strip()
            place_kind = form.cleaned_data.get("pirate_place_kind") or "other"
            city = form.cleaned_data.get("city") or ""
            write_about = form.cleaned_data.get("write_about") or ""
            email = form.cleaned_data.get("email") or ""

            with transaction.atomic():
                place = None
                if pirate_addr:
                    place, _ = Place.objects.get_or_create(
                        name=pirate_addr, city=city, defaults={"kind": place_kind},
                    )
                # Matching public identifiers do not prove profile ownership.
                person, _ = Person.objects.get_or_create(
                    nickname=nickname, pirate_place=place,
                    defaults={"city": city, "write_about": write_about, "email": email},
                )
                # Every request keeps its own prompt, including repeat requests.
                LetterConcept.objects.create(
                    title=f"Letter for {nickname}", write_prompt=write_about,
                    destination_place=place, destination_city=city, created_for=person,
                )
            return render(request, "people/request_thanks.html", {"nickname": nickname})
        return render(request, "people/request_a_letter.html", {"form": form})
    return render(request, "people/request_a_letter.html", {"form": RequestALetterForm()})
