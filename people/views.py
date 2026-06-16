from django.shortcuts import render, redirect, get_object_or_404
from .forms import RecipientSignupForm
from .models import Person
from django.contrib.auth.decorators import user_passes_test


def write_home(request):
    if request.method == "POST":
        form = RecipientSignupForm(request.POST)
        if form.is_valid():
            person, concept = form.save(user=request.user)
            return redirect("write_thanks", pk=person.pk)
    else:
        form = RecipientSignupForm()

    return render(request, "write_home.html", {"form": form})


def write_thanks(request, pk: int):
    person = get_object_or_404(Person, pk=pk)
    return render(request, "write_thanks.html", {"person": person})


def is_collaborator(user):
    return user.is_authenticated and getattr(user, "is_collaborator", False)


@user_passes_test(is_collaborator)
def recipient_list(request):
    people = Person.objects.order_by("-created_at")[:200]
    return render(request, "recipient_list.html", {"people": people})


def request_a_letter(request):
    """
    Public intake form — no login required.
    Anyone can submit themselves to receive a Pirate Mail letter.
    """
    if request.method == "POST":
        nickname     = (request.POST.get("nickname") or "").strip() or "A Stranger"
        pirate_addr  = (request.POST.get("pirate_address") or "").strip()
        city         = (request.POST.get("city") or "").strip()
        state        = (request.POST.get("state") or "").strip()
        region       = (request.POST.get("region") or "").strip()
        write_about  = (request.POST.get("write_about") or "").strip()
        social_place = (request.POST.get("social_place_name") or "").strip()
        email        = (request.POST.get("email") or "").strip()

        Person.objects.create(
            nickname=nickname,
            social_place_name=pirate_addr,
            city=city,
            state=state,
            region=region,
            write_about=write_about,
            email=email,
        )
        return redirect("request_letter_thanks")

    return render(request, "people/request_a_letter.html")


def request_letter_thanks(request):
    """
    Standalone thank-you page after a letter request is submitted.
    """
    return render(request, "people/request_thanks.html")
