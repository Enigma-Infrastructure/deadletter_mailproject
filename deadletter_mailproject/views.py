from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.urls import reverse
from accounts.services import can_review_participants

def home(request):
    return render(request, 'deadletter_info.html')

@staff_member_required
def admin_hub(request):
    sections = [
        {'title': 'Django Admin', 'links': [
            {'label': 'Site admin', 'url': '/admin/'},
        ]},
        {'title': 'Production & Review Pipeline', 'links': [
            {'label': 'Content review queue (moderation)', 'url': '/letters/review/queue/'},
            {'label': 'Print queue (unprinted letters)', 'url': '/letters/print/queue/'},
        ]},
        {'title': 'Public entry points', 'links': [
            {'label': 'Request a letter (intake)', 'url': '/write/request/'},
            {'label': 'Write & Read desk', 'url': '/letters/desk/'},
            {'label': 'Carry / Track', 'url': '/letters/carry/'},
            {'label': 'Scan a stamp', 'url': '/scan/'},
            {'label': 'Courier leaderboard', 'url': '/leaderboard/'},
        ]},
        {'title': 'Domain admin', 'links': [
            {'label': 'People (recipients)', 'url': '/admin/people/person/'},
            {'label': 'Pirate mail places', 'url': '/admin/people/place/'},
            {'label': 'Letter concepts', 'url': '/admin/letters/letterconcept/'},
            {'label': 'Letter instances', 'url': '/admin/letters/letterinstance/'},
            {'label': 'Stamps', 'url': '/admin/letters/stamp/'},
            {'label': 'Stamp updates', 'url': '/admin/letters/stampupdate/'},
            {'label': 'Letter hops', 'url': '/admin/letters/letterhop/'},
            {'label': 'Topics', 'url': '/admin/topics/topic/'},
            {'label': 'Media items', 'url': '/admin/media_app/mediaitem/'},
        ]},
    ]
    account_links = []
    if can_review_participants(request.user):
        account_links.append({'label': 'Review participants', 'url': reverse('admin:accounts_user_changelist') + '?participant_status__exact=pending'})
    if request.user.has_perm('accounts.view_registrationsource') or request.user.has_perm('accounts.change_registrationsource'):
        account_links.append({'label': 'Registration sources', 'url': reverse('admin:accounts_registrationsource_changelist')})
    if account_links:
        sections.insert(1, {'title': 'Participant accounts', 'links': account_links})
    return render(request, 'admin_hub.html', {'sections': sections})
