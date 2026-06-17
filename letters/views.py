# letters/views.py

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from people.models import LetterRequest
from .forms import LetterBodyForm
from .models import LetterInstance, LetterHop
import uuid
from django.utils import timezone


# --------------------------------------------------
# Admin hub
# --------------------------------------------------

@staff_member_required
def admin_hub(request):
    sections = [
        {
            "title": "Django Admin",
            "links": [{"label": "Site admin", "url": "/admin/"}],
        },
        {
            "title": "Public entry points",
            "links": [
                {"label": "Read Letters",   "url": "/letters/read/"},
                {"label": "Get a Letter",   "url": "/write/request/"},
                {"label": "Write a Letter", "url": "/letters/write/queue/"},
                {"label": "Carry / Track",  "url": "/letters/carry/"},
            ],
        },
        {
            "title": "Domain admin",
            "links": [
                {"label": "Letter requests",   "url": "/admin/people/letterrequest/"},
                {"label": "Letter instances",  "url": "/admin/letters/letterinstance/"},
                {"label": "Letter hops",       "url": "/admin/letters/letterhop/"},
                {"label": "Media items",       "url": "/admin/media_app/mediaitem/"},
            ],
        },
    ]
    return render(request, "admin_hub.html", {"sections": sections})


# --------------------------------------------------
# Deprecated desk routes — safe redirects
# --------------------------------------------------

def write_read_home(request):
    return redirect("home")

def desk_read_list(request):
    return redirect("letter_read_list")

def quick_write_start(request):
    return redirect("letter_write_queue")

def quick_write_letter(request, pk):
    return redirect("letter_write_queue")


# --------------------------------------------------
# Write queue — pick a pending request and write to it
# --------------------------------------------------

def letter_write_queue(request):
    """
    Shows all pending LetterRequests that haven't been written yet.
    Writer picks one and claims it.
    """
    requests = (
        LetterRequest.objects
        .filter(status='pending', is_active=True)
        .order_by('-created_at')
    )
    return render(request, "letter_write_queue.html", {"requests": requests})


def letter_write_claim(request, pk: int):
    """
    Writer writes the letter for a specific LetterRequest.
    On save: creates LetterInstance, marks request as 'written'.
    """
    letter_request = get_object_or_404(LetterRequest, pk=pk, is_active=True)

    if request.method == "POST":
        form = LetterBodyForm(request.POST)
        if form.is_valid():
            instance = LetterInstance.objects.create(
                request=letter_request,
                body_text=form.cleaned_data["body_text"],
                is_public=True,
                written_by=request.user if request.user.is_authenticated else None,
            )
            # Advance the request status
            letter_request.status = 'written'
            letter_request.save(update_fields=['status'])
            return redirect("letter_write_confirm", code=instance.code)
    else:
        form = LetterBodyForm()

    return render(
        request,
        "letter_write_claim.html",
        {"letter_request": letter_request, "form": form},
    )


def letter_write_confirm(request, code: str):
    letter = get_object_or_404(LetterInstance, code=code)
    return render(request, "letter_write_confirm.html", {"letter": letter})


# --------------------------------------------------
# Public letter pages
# --------------------------------------------------

def letter_public_page(request, code: str):
    letter = get_object_or_404(
        LetterInstance.objects.select_related("request"),
        code=code,
    )
    return render(request, "letter_public.html", {"letter": letter})


def letter_print_view(request, code: str):
    letter = get_object_or_404(LetterInstance, code=code, is_public=True)
    public_url = request.build_absolute_uri(f"/letters/l/{letter.code}/")
    return render(request, "letters/letter_print.html",
                  {"letter": letter, "public_url": public_url})


def print_queue(request):
    letters = (
        LetterInstance.objects
        .filter(is_public=True, hops__isnull=True)
        .select_related("request")
        .order_by("-created_at")
    )
    return render(request, "letters/print_queue.html", {"letters": letters})


def print_batch(request):
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
        return render(request, "letters/print_batch_confirm.html",
                      {"letters": batch_letters, "batch_id": batch_id,
                       "batch_qr_url": batch_qr_url})
    return redirect("print_queue")


# --------------------------------------------------
# Carry / hops
# --------------------------------------------------

def carry_list(request):
    city_filter = request.GET.get("city", "")
    nearby_letters = (
        LetterInstance.objects
        .filter(is_public=True, hops__status="waiting",
                hops__city__icontains=city_filter)
        .distinct()
        .select_related("request")
        .order_by("-hops__created_at")
    )
    return render(request, "letters/carry_list.html", {"letters": nearby_letters})


def letter_hop_create(request, code=None, batch_id=None):
    letter = None
    batch_letters = []

    if code:
        letter = get_object_or_404(LetterInstance, code=code, is_public=True)
    elif batch_id:
        pending = request.session.get("pending_batch", {})
        if pending.get("batch_id") == batch_id:
            batch_letters = LetterInstance.objects.filter(pk__in=pending["letters"])

    if request.method == "POST":
        print_city  = request.POST.get("print_city", "")
        print_venue = request.POST.get("print_venue", "")

        if letter and not letter.hops.exists():
            LetterHop.objects.create(
                letter=letter, status="waiting",
                city=print_city, venue_hint=print_venue,
                notes=f"Printed {print_city}",
                updated_by=request.user if request.user.is_authenticated else None,
            )
        elif batch_letters:
            for l in batch_letters:
                if not l.hops.exists():
                    LetterHop.objects.create(
                        letter=l, status="waiting",
                        city=print_city, venue_hint=print_venue,
                        notes=f"Batch printed {print_city}",
                        updated_by=request.user if request.user.is_authenticated else None,
                    )
            if "pending_batch" in request.session:
                del request.session["pending_batch"]
        return redirect("carry_list")

    return render(request, "letters/letter_hop_form.html",
                  {"letter": letter, "batch_letters": batch_letters})


# --------------------------------------------------
# Read / browse
# --------------------------------------------------

def letter_read_list(request):
    q = request.GET.get("q", "")

    qs = (
        LetterInstance.objects
        .filter(is_public=True, body_text__gt="")
        .select_related("request")
        .order_by("-created_at")
    )

    if q:
        qs = qs.filter(
            Q(body_text__icontains=q)
            | Q(request__nickname__icontains=q)
            | Q(request__write_about__icontains=q)
        )

    return render(request, "letter_read_list.html",
                  {"letters": qs[:100], "q": q})
