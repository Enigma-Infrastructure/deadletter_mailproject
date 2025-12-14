# letters/views.py - CLEAN VERSION
import uuid
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.db.models import Q
from django.utils import timezone
from .models import LetterInstance, LetterHop, LetterConcept
from people.models import Person
from topics.models import Topic
from .forms import LetterBodyForm

# Existing views (keep as-is)
def letter_public_page(request, code: str):
    letter = get_object_or_404(
        LetterInstance.objects.select_related("concept", "recipient"),
        code=code,
    )
    return render(request, "letter_public.html", {"letter": letter})

@login_required
def letter_write_queue(request):
    concepts = (
        LetterConcept.objects.filter(instances__isnull=True)
        .select_related("created_for")
        .order_by("-created_at")
    )
    return render(request, "letter_write_queue.html", {"concepts": concepts})

@login_required
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
                created_by=request.user,
            )
            return redirect("letter_write_confirm", code=instance.code)
    else:
        form = LetterBodyForm()

    return render(
        request,
        "letter_write_claim.html",
        {"concept": concept, "person": person, "form": form},
    )

@login_required
def letter_write_confirm(request, code: str):
    letter = get_object_or_404(LetterInstance, code=code)
    return render(request, "letter_write_confirm.html", {"letter": letter})

# Print views
def letter_print_view(request, code):
    """Print single letter envelope + body (no hop creation)."""
    letter = get_object_or_404(LetterInstance, code=code, is_public=True)
    public_url = request.build_absolute_uri(f"/l/{letter.code}/")
    return render(request, 'letters/letter_print.html', {
        'letter': letter, 
        'public_url': public_url
    })

def print_queue(request):
    letters = LetterInstance.objects.filter(
        is_public=True, 
        hops__isnull=True  # Unprinted
    ).select_related('recipient').order_by('-created_at')
    return render(request, 'letters/print_queue.html', {'letters': letters})

def print_batch(request):
    if request.method == 'POST':
        batch_letters = LetterInstance.objects.filter(pk__in=request.POST.getlist('letters'))
        batch_id = f"batch-{uuid.uuid4().hex[:8]}-{timezone.now().strftime('%Y%m%d')}"
        request.session['pending_batch'] = {
            'letters': [l.pk for l in batch_letters],
            'batch_id': batch_id,
        }
        return render(request, 'letters/print_batch_confirm.html', {
            'letters': batch_letters, 
            'batch_id': batch_id,
            'batch_qr_url': request.build_absolute_uri(f"/batch/{batch_id}/confirm/")
        })
    return redirect('print_queue')

# Carry views
def carry_list(request):
    city_filter = request.GET.get('city', '')
    nearby_letters = LetterInstance.objects.filter(
        is_public=True,
        hops__status='waiting',
        hops__city__icontains=city_filter
    ).distinct().select_related('recipient', 'hops').order_by('-hops__created_at')
    return render(request, 'letters/carry_list.html', {'letters': nearby_letters})

def letter_hop_create(request, code=None, batch_id=None):
    letter = None
    batch_letters = []
    
    if code:
        letter = get_object_or_404(LetterInstance, code=code, is_public=True)
    elif batch_id:
        pending = request.session.get('pending_batch', {})
        if pending.get('batch_id') == batch_id:
            batch_letters = LetterInstance.objects.filter(
                pk__in=pending['letters']
            )
    
    if request.method == 'POST':
        print_city = request.POST.get('print_city', '')
        print_venue = request.POST.get('print_venue', '')
        
        if letter and not letter.hops.exists():
            LetterHop.objects.create(
                letter=letter,
                status='waiting',
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
                        status='waiting',
                        city=print_city,
                        venue_hint=print_venue,
                        notes=f"Batch printed {print_city}",
                        updated_by=request.user if request.user.is_authenticated else None,
                    )
            # Clear session
            if 'pending_batch' in request.session:
                del request.session['pending_batch']
        
        return redirect('carry_list')
    
    context = {'letter': letter, 'batch_letters': batch_letters}
    return render(request, 'letters/letter_hop_form.html', context)

# Existing read list
def letter_read_list(request):
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
        {"letters": letters, "topics": topics, "selected_topic": topic_id, "q": q},
    )
