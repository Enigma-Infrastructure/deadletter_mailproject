from django.contrib.auth.decorators import user_passes_test
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
    """
    Public intake form — no login required. This is the single entry
    point for "put your name on an envelope".

    The pirate mail address is a social-network location (bar, cafe,
    camp, venue...) where this person can be found — not a postal
    address. Stored as a structured Place.

    Also creates the LetterConcept (prompt) so the request appears in
    the write queue for other participants.
    """
    if request.method == "POST":
        form = RequestALetterForm(request.POST)
        if form.is_valid():
            nickname    = form.cleaned_data["nickname"].strip() or "A Stranger"
            pirate_addr = form.cleaned_data["pirate_address"].strip()
            place_kind  = form.cleaned_data.get("pirate_place_kind") or "other"
            city        = form.cleaned_data.get("city") or ""
            write_about = form.cleaned_data.get("write_about") or ""
            email       = form.cleaned_data.get("email") or ""

            place = None
            if pirate_addr:
                place, _ = Place.objects.get_or_create(
                    name=pirate_addr,
                    city=city,
                    defaults={"kind": place_kind},
                )

            # Identity is the unique pair (nickname, pirate_place).
            # If this pair already exists, update the existing entry.
            person, created = Person.objects.get_or_create(
                nickname=nickname,
                pirate_place=place,
                defaults={
                    "city": city,
                    "write_about": write_about,
                    "email": email,
                },
            )
            if not created:
                person.write_about = write_about
                person.email = email
                person.save(update_fields=["write_about", "email"])

            LetterConcept.objects.create(
                title=f"Letter for {nickname}",
                write_prompt=write_about,
                destination_place=place,
                destination_city=city,
                created_for=person,
            )

            return render(request, "people/request_thanks.html", {"nickname": nickname})
        # Form invalid — re-render with errors
        return render(request, "people/request_a_letter.html", {"form": form})

    return render(request, "people/request_a_letter.html", {"form": RequestALetterForm()})
