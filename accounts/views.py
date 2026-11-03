from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .forms import PreferencesForm, RegistrationForm
from .models import RegistrationSource, ReputationEvent

def leaderboard(request):
    return render(request, 'leaderboard.html', {'leaders': ReputationEvent.leaderboard(limit=25)})

@never_cache
@require_http_methods(['GET', 'POST'])
def register(request):
    if request.user.is_authenticated:
        return redirect('participant_status')
    form = RegistrationForm(request.POST if request.method == 'POST' else None, initial={'source': request.GET.get('source', '')})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            source = form.registration_source
            if source is not None:
                source = RegistrationSource.objects.select_for_update().filter(pk=source.pk).first()
                if source is None or not source.is_available():
                    form.add_error('source', 'This source is no longer available.')
                else:
                    form.registration_source = source
            if not form.errors:
                user = form.save()
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect('participant_status')
    return render(request, 'registration/register.html', {'form': form})

@never_cache
@login_required
@require_http_methods(['GET'])
def participant_status(request):
    request.user.refresh_from_db(fields=['participant_status'])
    my_requests = request.user.letter_requests_owned.select_related('recipient', 'destination_place').order_by('-created_at')[:20]
    my_letters = request.user.letters_written.select_related('recipient', 'destination_place', 'request').prefetch_related('instances', 'instances__stamps').order_by('-created_at')[:20]
    return render(
        request,
        'registration/participant_status.html',
        {
            'status': request.user.participant_status,
            'my_requests': my_requests,
            'my_letters': my_letters,
        },
    )

@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def preferences(request):
    form = PreferencesForm(request.POST if request.method == 'POST' else None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('account_preferences')
    return render(request, 'registration/preferences.html', {'form': form})
