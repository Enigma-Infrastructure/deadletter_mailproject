"""Read-only policy adapters; not yet wired to legacy public routes.

Pass the server-authenticated user, never POST/GET claims. Querysets contain
full models, NOT public response payloads: social addresses need a separate gate.
Admin/owner editing permissions are outside these audience decisions.
"""
from django.contrib.auth import get_user_model
from django.db.models import Q

from .access_policy import ContentAccess, Viewer, can_read_social_address
from .models import Letter, LetterRequest


def persisted_viewer(user, using='default'):
    if user is None or not getattr(user, 'is_authenticated', False) or user.pk is None:
        return Viewer()
    state = get_user_model().objects.using(using).filter(pk=user.pk).values('is_active', 'participant_status').first()
    if state is None:
        return Viewer()
    return Viewer(authenticated=True, active=state['is_active'], status=state['participant_status'])


def _audience(viewer, prefix=''):
    condition = Q(**{prefix + 'is_published': True, prefix + 'requested_visibility__in': ['public', 'participants_only']})
    if not viewer.approved:
        condition &= Q(**{prefix + 'requested_visibility': 'public', prefix + 'automatically_restricted': False})
    return condition


def readable_requests(user, using='default'):
    return LetterRequest.objects.using(using).filter(_audience(persisted_viewer(user, using)))


def readable_letters(user, using='default'):
    viewer = persisted_viewer(user, using)
    return Letter.objects.using(using).filter(_audience(viewer)).filter(Q(request_id__isnull=True) | _audience(viewer, 'request__'))


def can_read_saved_request(user, request_id, using='default'):
    return readable_requests(user, using).filter(pk=request_id).exists()


def can_read_saved_letter(user, letter_id, using='default'):
    return readable_letters(user, using).filter(pk=letter_id).exists()


def can_read_request_address(user, request_id, using='default'):
    viewer = persisted_viewer(user, using)
    row = LetterRequest.objects.using(using).filter(pk=request_id).values('requested_visibility', 'automatically_restricted', 'is_published').first()
    if row is None:
        return False
    return can_read_social_address(viewer, ContentAccess(row['requested_visibility'], row['automatically_restricted'], row['is_published']))


def can_read_letter_address(user, letter_id, using='default'):
    viewer = persisted_viewer(user, using)
    if not viewer.approved:
        return False
    return Letter.objects.using(using).filter(pk=letter_id).filter(_audience(viewer)).filter(Q(request_id__isnull=True) | _audience(viewer, 'request__')).exists()
