# letters/views.py

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import View
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import ReputationEvent
from media_app.models import MediaItem
from people.models import Person, Place
from topics.models import Topic
from .forms import LetterBodyForm, ScanUpdateForm
from .models import LetterConcept, LetterInstance, LetterHop, Stamp, StampUpdate
from .serializers import LetterInstanceSerializer


# --------------------------------------------------
# Public write & read desk
# --------------------------------------------------

def write_read_home(request):
    """
    Writing desk: shows pending letters (concepts without instances).
    Selecting one goes to the claim page where the writer writes the body.
    """
    concepts = (
        LetterConcept.objects.filter(instances__isnull=True)
        .select_related("created_for", "destination_place")
        .order_by("-created_at")
    )
    return render(
        request,
        "desk/write_read_home.html",
        {"concepts": concepts},
    )


# --------------------------------------------------
# Original writer flows (concept → instance)
# --------------------------------------------------

def letter_write_queue(request):
    """
    Concepts that don't yet have any instances = letters to be written.
    This remains public for the demo; collaborators can still use it.
    """
    topic_hint = request.GET.get("topic_custom") or request.GET.get("topic") or ""

    concepts = (
        LetterConcept.objects.filter(instances__isnull=True)
        .select_related("created_for", "destination_place")
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
                current_place=concept.destination_place,
                current_city=concept.destination_city or (person.city if person else ""),
                status="waiting_print",
                origin="online",
                needs_printing=True,
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
# Physical production pipeline (digital -> print -> stamp)
# --------------------------------------------------

@staff_member_required
def print_queue(request):
    """Letters that exist digitally but still need printing/enveloping."""
    letters = (
        LetterInstance.objects.filter(status="waiting_print", is_public=True)
        .select_related("recipient", "concept", "current_place")
        .order_by("-created_at")
    )
    return render(request, "letters/print_queue.html", {"letters": letters})


@staff_member_required
def print_batch(request):
    """
    Step 1: select letters to print. Shows a confirmation page.
    Does NOT change status or issue stamps yet.
    """
    if request.method == "POST":
        ids = request.POST.getlist("letters")
        batch_letters = list(
            LetterInstance.objects.filter(pk__in=ids, needs_printing=True)
            .select_related("recipient", "current_place")
        )
        if not batch_letters:
            messages.info(request, "No unprinted letters were selected.")
            return redirect("print_queue")

        return render(
            request,
            "letters/print_batch_confirm.html",
            {"batch": batch_letters},
        )

    return redirect("print_queue")


@staff_member_required
def print_confirm(request):
    """
    Step 2: confirm print complete. Changes status to waiting_carrier,
    sets needs_printing=False, printed_at, and issues a stamp for each letter.
    """
    if request.method == "POST":
        ids = request.POST.getlist("letters")
        batch_letters = list(
            LetterInstance.objects.filter(pk__in=ids, needs_printing=True)
            .select_related("recipient", "current_place")
        )
        if not batch_letters:
            messages.info(request, "No letters to confirm.")
            return redirect("print_queue")

        stamps = []
        now = timezone.now()
        user = request.user if request.user.is_authenticated else None
        for letter in batch_letters:
            stamp, _created = Stamp.objects.get_or_create(
                letter=letter,
                is_active=True,
                defaults={"issued_by": user},
            )
            letter.needs_printing = False
            letter.printed_at = now
            letter.status = "waiting_carrier"
            letter.save(update_fields=["needs_printing", "printed_at", "status"])
            stamps.append((letter, stamp))

        messages.success(request, f"{len(stamps)} letters confirmed as printed.")
        return redirect("print_queue")

    return redirect("print_queue")


def letter_print_view(request, code: str):
    """Print single letter envelope + body, with its stamp QR."""
    letter = get_object_or_404(
        LetterInstance.objects.select_related("recipient", "current_place"),
        code=code,
        is_public=True,
    )
    stamp = letter.stamps.filter(is_active=True).first()
    if stamp:
        scan_url = request.build_absolute_uri(f"/scan/{stamp.number}/")
    else:
        scan_url = request.build_absolute_uri(f"/letters/l/{letter.code}/")
    return render(
        request,
        "letters/letter_print.html",
        {"letter": letter, "stamp": stamp, "scan_url": scan_url},
    )


# --------------------------------------------------
# Reactive stamp scans (public, no login required)
# --------------------------------------------------

RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 5     # max updates per window per IP


def _rate_limit_check(request):
    """Simple per-IP rate limit for anonymous scan updates.
    Returns True if the request is within the limit, False otherwise."""
    ip = request.META.get("REMOTE_ADDR", "")
    if not ip:
        return True  # no IP available, allow
    # Use a simple in-memory cache keyed by IP
    # For production, replace with Redis or similar.
    cache_key = f"scan_rate_{ip}"
    from django.core.cache import cache
    count = cache.get(cache_key, 0)
    if count >= RATE_LIMIT_MAX:
        return False
    cache.set(cache_key, count + 1, RATE_LIMIT_WINDOW)
    return True


def scan_home(request):
    """
    General QR landing site. Anyone scanning the stamp QR ends up here
    (or directly at /scan/<number>/) and types in the stamp's unique
    number to see and update the letter.
    """
    if request.method == "POST":
        number = (request.POST.get("number") or "").strip().upper()
        if number:
            return redirect("scan_stamp", number=number)
        messages.error(request, "Please enter the number printed on the stamp.")
    return render(request, "scan_home.html")


def scan_stamp(request, number: str):
    """
    Public, reactive letter page: shows the letter's journey and lets
    anyone who physically has/sees the letter post an update — status,
    note, photo, Instagram tag — no account required.
    """
    stamp = get_object_or_404(Stamp, number__iexact=number, is_active=True)
    letter = stamp.letter
    updates = stamp.updates.select_related("place", "media", "submitted_by")

    if request.method == "POST":
        if not _rate_limit_check(request):
            messages.error(request, "Too many updates from your address. Please wait a minute.")
            return redirect("scan_stamp", number=stamp.number)

        form = ScanUpdateForm(request.POST, request.FILES)
        if not form.is_valid():
            # Re-render with errors
            updates = stamp.updates.select_related("place", "media", "submitted_by")
            return render(
                request,
                "scan_stamp.html",
                {
                    "stamp": stamp,
                    "letter": letter,
                    "updates": updates,
                    "form": form,
                },
            )

        kind = form.cleaned_data["kind"]
        if kind not in dict(StampUpdate.KIND_CHOICES):
            kind = "spotted"
        note = form.cleaned_data.get("note", "").strip()
        place_name = form.cleaned_data.get("place_name", "").strip()
        place_kind = form.cleaned_data.get("place_kind", "other")
        city = form.cleaned_data.get("city", "").strip()
        instagram = form.cleaned_data.get("instagram_handle", "").strip().lstrip("@")
        photo = form.cleaned_data.get("photo")
        user = request.user if request.user.is_authenticated else None

        place = None
        if place_name:
            place, _ = Place.objects.get_or_create(
                name=place_name,
                city=city,
                defaults={"kind": place_kind, "created_by": user},
            )

        media = None
        if photo:
            media_kind = {
                "picked_up": "carrier",
                "delivered": "arrival",
                "left_at_place": "arrival",
            }.get(kind, "other")
            media = MediaItem.objects.create(
                letter=letter,
                file=photo,
                kind=media_kind,
                caption=note,
                hashtags="#piratemail #deadletter",
                uploaded_by=user,
            )

        StampUpdate.objects.create(
            stamp=stamp,
            kind=kind,
            note=note,
            place=place,
            instagram_handle=instagram,
            media=media,
            submitted_by=user,
        )

        # Movement kinds also drive the courier chain and letter state.
        if kind in ("picked_up", "left_at_place", "delivered"):
            LetterHop.objects.create(
                letter=letter,
                status={
                    "picked_up": "picked_up",
                    "left_at_place": "left_at_location",
                    "delivered": "delivered",
                }[kind],
                place=place,
                city=city,
                notes=note,
                updated_by=user,
            )
            letter.status = {
                "picked_up": "traveling",
                "left_at_place": "left",
                "delivered": "delivered",
            }[kind]
            if place:
                letter.current_place = place
            if city:
                letter.current_city = city
            letter.save()

        # Reputation layer: credit logged-in couriers.
        if kind in ("picked_up", "left_at_place", "delivered", "spotted"):
            ReputationEvent.award(user=user, reason=kind, letter=letter)
        if photo:
            ReputationEvent.award(user=user, reason="photo", letter=letter)
        if note and not photo:
            ReputationEvent.award(user=user, reason="note", letter=letter)

        messages.success(request, "Thanks for keeping this letter moving!")
        return redirect("scan_stamp", number=stamp.number)

    return render(
        request,
        "scan_stamp.html",
        {
            "stamp": stamp,
            "letter": letter,
            "updates": updates,
        },
    )


# --------------------------------------------------
# Carry / courier list
# --------------------------------------------------

def carry_list(request):
    """
    Letters that have been printed/stamped and are ready to be picked
    up or are in transit — the courier-facing list.
    """
    city_filter = request.GET.get("city", "")

    qs = (
        LetterInstance.objects.filter(
            is_public=True,
            stamps__is_active=True,
            status__in=["waiting_carrier", "traveling", "left"],
        )
        .select_related("recipient", "current_place")
        .distinct()
    )
    if city_filter:
        qs = qs.filter(
            Q(current_city__icontains=city_filter)
            | Q(current_place__city__icontains=city_filter)
        )
    letters = qs.order_by("-printed_at", "-created_at")[:100]

    return render(request, "letters/carry_list.html", {"letters": letters})


# --------------------------------------------------
# API (moved from the old routing app)
# --------------------------------------------------

class LettersInMyAreaAPIView(APIView):
    """JSON list of stamped letters in play, filtered by city/place."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        city = request.query_params.get("city")
        place = request.query_params.get("place")

        qs = LetterInstance.objects.filter(
            is_public=True,
            stamps__is_active=True,
            status__in=["waiting_carrier", "traveling", "left"],
        ).select_related("current_place", "recipient")

        if city:
            qs = qs.filter(
                Q(current_place__city__iexact=city) | Q(current_city__iexact=city)
            )
        if place:
            qs = qs.filter(current_place__name__icontains=place)

        serializer = LetterInstanceSerializer(qs.distinct()[:100], many=True)
        return Response(serializer.data)


# --------------------------------------------------
# Reader / browse
# --------------------------------------------------

def letter_public_page(request, code: str):
    """HTML page for QR scans: minimal story / info about the letter.

    Respects the explicit `is_public=False` opt-out: a letter that has been
    marked non-public is not readable here (404).
    """
    letter = get_object_or_404(
        LetterInstance.objects.select_related(
            "concept", "recipient", "recipient__pirate_place", "current_place"
        ),
        code=code,
        is_public=True,
    )
    return render(request, "letter_public.html", {"letter": letter})


def letter_read_list(request):
    """
    Public browse/read view: filter by topic, text, city/destination.
    Display modes: list or tile. Paginated.
    """
    topic_id = request.GET.get("topic")
    q = request.GET.get("q", "")
    city_filter = request.GET.get("city", "")
    view = request.GET.get("view", "list")
    page = request.GET.get("page", 1)

    qs = (
        LetterInstance.objects.filter(is_public=True, body_text__gt="")
        .select_related("concept", "recipient", "recipient__pirate_place")
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

    if city_filter:
        qs = qs.filter(
            Q(recipient__city__icontains=city_filter)
            | Q(recipient__pirate_place__city__icontains=city_filter)
            | Q(current_place__city__icontains=city_filter)
        )

    topics = Topic.objects.order_by("name")
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(page)

    return render(
        request,
        "letter_read_list.html",
        {
            "letters": page_obj,
            "topics": topics,
            "selected_topic": topic_id,
            "q": q,
            "city_filter": city_filter,
            "view": view,
            "page_obj": page_obj,
            "total_count": paginator.count,
        },
    )


def desk_read_list(request):
    """
    Desk-only reading view: show recent public letters
    using the desk skin.
    """
    letters = (
        LetterInstance.objects.filter(is_public=True, body_text__gt="")
        .select_related("concept", "recipient", "recipient__pirate_place")
        .order_by("-created_at")[:50]
    )
    return render(request, "desk/desk_read_list.html", {"letters": letters})
