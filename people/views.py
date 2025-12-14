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