from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from letters.access_policy import Viewer
from .models import User

def viewer_for_user(user):
    if not getattr(user, 'is_authenticated', False) or user.pk is None:
        return Viewer()
    state = User.objects.filter(pk=user.pk).values('is_active', 'participant_status').first()
    if state is None:
        return Viewer()
    return Viewer(authenticated=True, active=state['is_active'], status=state['participant_status'])

def can_review_participants(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    actor = User.objects.filter(pk=user.pk).first()
    return bool(actor and actor.is_active and actor.is_staff and actor.has_perm('accounts.change_user'))

@transaction.atomic
def review_participant(*, reviewer, participant_id, status):
    if not can_review_participants(reviewer):
        raise PermissionDenied
    if status not in {'approved', 'rejected', 'suspended'}:
        raise ValidationError('Unsupported review action.')
    participant = User.objects.select_for_update().get(pk=participant_id)
    participant.participant_status = status
    participant.participant_reviewed_by_id = reviewer.pk
    participant.participant_reviewed_at = timezone.now()
    participant.save(update_fields=['participant_status', 'participant_reviewed_by', 'participant_reviewed_at'])
    return participant
