# letters/views.py

import uuid

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from people.models import Person
from topics.models import Topic
from .forms import LetterBodyForm
from .models import LetterConcept, LetterInstance, LetterHop


# --------------------------------------------------
# Project home / admin hub
# --------------------------------------------------

def home(request):
    """Very simple project home; usually base shell."""
    return render(request, "base.html")


@staff_member_required
def admin_hub(request):
    """Central place to link to admin and project areas."""
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


# --------------------------------------------------
# Public write & read desk (cyberpunk subsite)
# --------------------------------------------------

def write_read_home(request):
    """
    Public landing page used at events/parties:
    - choose a topic and start a letter
    - or go to the read/browse view
    """
    return render(request, "cyberpunk/write_read_home.html")


def quick_write_start(request):
    """
    Take a chosen topic and create a one-off LetterConcept,
    then redirect straight into the quick-write letter view.
    """
    topic = request.GET.get("topic_custom") or request.GET.get("topic") or ""
    topic = (topic or "").strip()
    if not topic:
        return redirect("write_read_home")

    concept = LetterConcept.objects.create(
        title=topic,
        write_prompt=topic,
        created_for=None,
    )
    return redirect("quick_write_letter", pk=concept.pk)


def quick_write_letter(request, pk: int):
    """
    Write a letter directly for a one-off concept, with:
    - name/alias mapped to Person.nickname
    - optional email for continued interest (stored on Person, not shown publicly)
    """
    concept = get_object_or_404(LetterConcept, pk=pk)

    if request.method == "POST":
        form = LetterBodyForm(request.POST)
        name = (request.POST.get("name_alias", "") or "").strip() or "Someone out there"
        email = (request.POST.get("continued_email", "") or "").strip()

        if form.is_valid():
            # Create/get the Person by nickname; update email if provided
            recipient, created = Person.objects.get_or_create(
                nickname=name,
                defaults={"city": "", "region": ""},
            )
            if email:
                recipient.email = email
                recipient.save(update_fields=["email"])

            LetterInstance.objects.create(
                concept=concept,
                recipient=recipient,
                body_text=form.cleaned_data["body_text"],
                current_city="",
                current_region="",
                current_state="",
                current_social_place_name="",
                status="waiting",
                created_by=request.user if request.user.is_authenticated else None,
            )
            return redirect("desk_read_list")
    else:
        form = LetterBodyForm()

    return render(
        request,
        "cyberpunk/quick_write_letter.html",
        {"concept": concept, "form": form},
    )



# --------------------------------------------------
# Original writer flows (concept → instance)
# --------------------------------------------------

def letter_write_queue(request):
    """
    Concepts that don’t yet have any instances = letters to be written.
    This remains public for the demo; collaborators can still use it.
    """
    topic_hint = request.GET.get("topic_custom") or request.GET.get("topic") or ""

    concepts = (
        LetterConcept.objects.filter(instances__isnull=True)
        .select_related("created_for")
        .order_by("-created_at")
    )
    return render(
        request,
        "letter_write_queue.html",
        {"concepts": concepts, "topic_hint": topic_hint},
    )


def letter_write_claim(request, pk: int):
    concept = get_object_or_404(LetterConcept, pk=pk)
    person = concept.created_for

    if request.method == "POST":
        form = LetterBodyForm(request.POST)
        if form.is_valid():
            instance = LetterInstance.objects.create(
                concept=concept,
                recipient=person,
                body_text=form.cleaned_data["body_text"],
                current_city=concept.destination_city or (person.city if person else ""),
                current_region=concept.destination_region or (person.region if person else ""),
                current_state=concept.destination_state or (person.state if person else ""),
                current_social_place_name=concept.destination_social_place_name,
                status="waiting",
                created_by=request.user if request.user.is_authenticated else None,
            )
            return redirect("letter_write_confirm", code=instance.code)
    else:
        form = LetterBodyForm()

    return render(
        request,
        "letter_write_claim.html",
        {"concept": concept, "person": person, "form": form},
    )


def letter_write_confirm(request, code: str):
    """Show confirmation + links after a letter instance is created."""
    letter = get_object_or_404(LetterInstance, code=code)
    return render(request, "letter_write_confirm.html", {"letter": letter})


# --------------------------------------------------
# Public letter + printing
# --------------------------------------------------

def letter_public_page(request, code: str):
    """HTML page for QR scans: minimal story / info about the letter."""
    letter = get_object_or_404(
        LetterInstance.objects.select_related("concept", "recipient"),
        code=code,
    )
    return render(request, "letter_public.html", {"letter": letter})


def letter_print_view(request, code: str):
    """Print single letter envelope + body (no hop creation)."""
    letter = get_object_or_404(LetterInstance, code=code, is_public=True)
    public_url = request.build_absolute_uri(f"/letters/l/{letter.code}/")
    return render(
        request,
        "letters/letter_print.html",
        {"letter": letter, "public_url": public_url},
    )


def print_queue(request):
    """List letters that have not yet had any hops (unprinted / unreleased)."""
    letters = (
        LetterInstance.objects.filter(is_public=True, hops__isnull=True)
        .select_related("recipient")
        .order_by("-created_at")
    )
    return render(request, "letters/print_queue.html", {"letters": letters})


def print_batch(request):
    """
    Create a batch from selected letters and show a page with:
    - per-letter print links
    - a final batch QR for first-hop confirmation.
    """
    if request.method == "POST":
        ids = request.POST.getlist("letters")
        batch_letters = LetterInstance.objects.filter(pk__in=ids)
        if not batch_letters:
            return redirect("print_queue")

        batch_id = f"batch-{uuid.uuid4().hex[:8]}-{timezone.now().strftime('%Y%m%d')}"
        request.session["pending_batch"] = {
            "letters": [l.pk for l in batch_letters],
            "batch_id": batch_id,
        }
        batch_qr_url = request.build_absolute_uri(f"/letters/batch/{batch_id}/confirm/")

        return render(
            request,
            "letters/print_batch_confirm.html",
            {"letters": batch_letters, "batch_id": batch_id, "batch_qr_url": batch_qr_url},
        )

    return redirect("print_queue")


# --------------------------------------------------
# Carry / hops
# --------------------------------------------------

def carry_list(request):
    """
    Letters whose latest hop is 'waiting', optionally filtered by city.
    Used as the carrier-facing list.
    """
    city_filter = request.GET.get("city", "")

    nearby_letters = (
        LetterInstance.objects.filter(
            is_public=True,
            hops__status="waiting",
            hops__city__icontains=city_filter,
        )
        .distinct()
        .select_related("recipient")
        .order_by("-hops__created_at")
    )
    return render(request, "letters/carry_list.html", {"letters": nearby_letters})


def letter_hop_create(request, code=None, batch_id=None):
    """
    Create a new hop:
    - single-letter mode: /letters/l/<code>/hop/
    - batch-confirm mode: /letters/batch/<batch_id>/confirm/
    """
    letter = None
    batch_letters = []

    if code:
        letter = get_object_or_404(LetterInstance, code=code, is_public=True)
    elif batch_id:
        pending = request.session.get("pending_batch", {})
        if pending.get("batch_id") == batch_id:
            batch_letters = LetterInstance.objects.filter(pk__in=pending["letters"])

    if request.method == "POST":
        print_city = request.POST.get("print_city", "")
        print_venue = request.POST.get("print_venue", "")

        if letter and not letter.hops.exists():
            LetterHop.objects.create(
                letter=letter,
                status="waiting",
                city=print_city,
                venue_hint=print_venue,
                notes=f"Printed {print_city}",
                updated_by=request.user if request.user.is_authenticated else None,
            )
        elif batch_letters:
            for l in batch_letters:
                if not l.hops.exists():
                    LetterHop.objects.create(
                        letter=l,
                        status="waiting",
                        city=print_city,
                        venue_hint=print_venue,
                        notes=f"Batch printed {print_city}",
                        updated_by=request.user if request.user.is_authenticated else None,
                    )
            if "pending_batch" in request.session:
                del request.session["pending_batch"]

        return redirect("carry_list")

    context = {"letter": letter, "batch_letters": batch_letters}
    return render(request, "letters/letter_hop_form.html", context)


# --------------------------------------------------
# Reader / browse
# --------------------------------------------------

def letter_read_list(request):
    """
    Public browse/read view: filter by topic and text, show letter bodies.
    """
    topic_id = request.GET.get("topic")
    q = request.GET.get("q", "")

    qs = (
        LetterInstance.objects.filter(is_public=True, body_text__gt="")
        .select_related("concept", "recipient")
        .prefetch_related("concept__letter_topics__topic")
        .order_by("-created_at")
    )

    if topic_id:
        qs = qs.filter(concept__letter_topics__topic_id=topic_id)

    if q:
        qs = qs.filter(
            Q(body_text__icontains=q)
            | Q(concept__title__icontains=q)
            | Q(concept__write_prompt__icontains=q)
            | Q(recipient__nickname__icontains=q)
        )

    topics = Topic.objects.order_by("name")
    letters = qs[:100]

    return render(
        request,
        "letter_read_list.html",
        {
            "letters": letters,
            "topics": topics,
            "selected_topic": topic_id,
            "q": q,
        },
    )

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
