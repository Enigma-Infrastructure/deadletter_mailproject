from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from letters.models import LetterConcept
from .forms import RequestALetterForm
from .models import Person, Place


def is_collaborator(user):
    return user.is_authenticated and getattr(user, 'is_collaborator', False)


@user_passes_test(is_collaborator)
def recipient_list(request):
    people = Person.objects.select_related('pirate_place').order_by('-created_at')[:200]
    return render(request, 'recipient_list.html', {'people': people})


@never_cache
def request_a_letter(request):
    """Create requests without collecting email or editing existing profiles."""
    if request.method == 'POST':
        from letters.ratelimit import check_rate_limit, rate_limit_response
        if not check_rate_limit(request, "intake_request", max_requests=15, window_seconds=60):
            return rate_limit_response()

        form = RequestALetterForm(request.POST)
        if form.is_valid():
            nickname = form.cleaned_data['nickname'].strip() or 'A Stranger'
            pirate_addr = form.cleaned_data['pirate_address'].strip()
            place_kind = form.cleaned_data.get('pirate_place_kind') or 'other'
            city = form.cleaned_data.get('city') or ''
            write_about = form.cleaned_data.get('write_about') or ''

            from letters.content_screening import screen_content
            is_restricted, restriction_reason = screen_content(write_about)

            with transaction.atomic():
                place = None
                if pirate_addr:
                    place, _ = Place.objects.get_or_create(
                        name=pirate_addr, city=city, defaults={'kind': place_kind},
                    )
                # Public identifiers and submitted email do not prove ownership.
                person, _ = Person.objects.get_or_create(
                    nickname=nickname, pirate_place=place,
                    defaults={'city': city, 'write_about': write_about},
                )
                # Keep each request's prompt. Account ownership is a later batch.
                concept = LetterConcept.objects.create(
                    title=f'Letter for {nickname}', write_prompt=write_about,
                    destination_place=place, destination_city=city, created_for=person,
                )
                from letters.models import LetterRequest
                destination_label = (place.name.strip() if place else '') + (f' · {city}' if city else '')
                LetterRequest.objects.create(
                    prompt=write_about,
                    recipient=person,
                    recipient_alias=nickname,
                    destination_place=place,
                    destination_city=city,
                    destination_label=destination_label,
                    concept=concept,
                    legacy_source=concept,
                    submitted_by=request.user if request.user.is_authenticated else None,
                    owner=request.user if request.user.is_authenticated else None,
                    requested_visibility='public',
                    automatically_restricted=is_restricted,
                    restriction_reason=restriction_reason,
                    is_published=not is_restricted,
                    is_open=True,
                )
            return render(request, 'people/request_thanks.html', {'nickname': nickname})
        return render(request, 'people/request_a_letter.html', {'form': form})
    return render(request, 'people/request_a_letter.html', {'form': RequestALetterForm()})
