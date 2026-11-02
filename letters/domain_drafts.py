"""Private draft workspace services. Not wired to routes; no admin bypass."""
from django.core.exceptions import PermissionDenied
from django.db import transaction

from accounts.models import ReputationEvent
from media_app.models import MediaItem
from .domain_access import persisted_viewer
from .domain_writes import _approved_actor, _identifier, _text, _visibility
from .models import Letter, LetterHop, LetterInstance, LetterRequest, Stamp


def owned_request_drafts(user, using='default'):
    qs = LetterRequest.objects.using(using).filter(is_published=False)
    if not persisted_viewer(user, using).approved:
        return qs.none()
    return qs.filter(owner_id=user.pk)


def authored_letter_drafts(user, using='default'):
    qs = Letter.objects.using(using).filter(is_published=False)
    if not persisted_viewer(user, using).approved:
        return qs.none()
    return qs.filter(writer_id=user.pk)


def _require_review_draft(row):
    if row is None or row.is_published or not row.automatically_restricted or row.restriction_reason != 'review_required':
        raise PermissionDenied('This draft is not available for editing.')


def edit_request_draft(user, *, request_id, prompt, requested_visibility=None, using='default'):
    with transaction.atomic(using=using):
        actor = _approved_actor(user, using)
        row = LetterRequest.objects.using(using).select_for_update().filter(pk=_identifier(request_id), owner_id=actor.pk).first()
        _require_review_draft(row)
        if row.legacy_source_id is not None or Letter.objects.using(using).filter(request_id=row.pk).exists():
            raise PermissionDenied('Historical requests and requests with responses require a separate revision workflow.')
        row.prompt = _text(prompt)
        row.requested_visibility = _visibility(requested_visibility, row.requested_visibility)
        row.save(using=using, update_fields=['prompt', 'requested_visibility'])
        return row


def edit_letter_draft(user, *, letter_id, body_text, requested_visibility=None, using='default'):
    with transaction.atomic(using=using):
        actor = _approved_actor(user, using)
        row = Letter.objects.using(using).select_for_update().filter(pk=_identifier(letter_id), writer_id=actor.pk).first()
        _require_review_draft(row)
        if row.finalized_at is not None:
            raise PermissionDenied('Finalized works require a separate revision workflow.')
        instances = list(LetterInstance.objects.using(using).select_for_update().filter(authored_letter_id=row.pk).order_by('pk'))
        if len(instances) != 1:
            raise PermissionDenied('Only a single staged physical draft can be edited.')
        instance = instances[0]
        if (instance.is_public or instance.printed_at is not None or not instance.needs_printing
                or instance.status != 'created' or instance.origin != 'online' or instance.concept_id is not None
                or instance.body_text != row.body_text):
            raise PermissionDenied('Physical production or legacy differences require a separate revision workflow.')
        if (Stamp.objects.using(using).filter(letter_id=instance.pk).exists()
                or LetterHop.objects.using(using).filter(letter_id=instance.pk).exists()
                or MediaItem.objects.using(using).filter(letter_id=instance.pk).exists()
                or ReputationEvent.objects.using(using).filter(letter_id=instance.pk).exists()):
            raise PermissionDenied('Recorded physical activity requires a separate revision workflow.')
        row.body_text = _text(body_text)
        row.requested_visibility = _visibility(requested_visibility, row.requested_visibility)
        row.save(using=using, update_fields=['body_text', 'requested_visibility'])
        instance.body_text = row.body_text
        instance.save(using=using, update_fields=['body_text'])
        return row, instance
