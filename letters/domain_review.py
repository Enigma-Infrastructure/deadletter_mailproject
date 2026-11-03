"""Content review, publication approval, and finalization services.

Requires active staff/reviewer authorization.
Enforces domain invariants:
- A letter cannot be published if its parent request is unpublished.
- Publishing a letter finalizes it (setting finalized_at) and unlocks its linked
  physical instance for the printing pipeline (is_public=True, status='waiting_print').
- Restricting content unpublishes it, marks automatically_restricted, and hides
  linked physical copies.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .domain_presentation import LETTER_FIELDS, REQUEST_FIELDS
from .domain_writes import _identifier, _text
from .models import Letter, LetterInstance, LetterRequest


def _reviewer(user, using):
    if user is None or not getattr(user, 'is_authenticated', False) or user.pk is None:
        raise PermissionDenied('Staff reviewer authentication required.')
    actor = get_user_model().objects.using(using).select_for_update().filter(pk=user.pk).first()
    if actor is None or not actor.is_active or not actor.is_staff:
        raise PermissionDenied('Staff reviewer authorization required.')
    return actor


def publish_request(user, request_id, *, using='default'):
    """Approve a LetterRequest for publication.

    Clears review restrictions and marks the request published.
    Returns the allowlisted card dictionary for the request.
    """
    with transaction.atomic(using=using):
        _reviewer(user, using)
        req = (
            LetterRequest.objects.using(using)
            .select_for_update()
            .filter(pk=_identifier(request_id))
            .first()
        )
        if req is None:
            raise ValidationError('Request not found.')

        req.is_published = True
        req.automatically_restricted = False
        req.restriction_reason = ''
        req.save(update_fields=['is_published', 'automatically_restricted', 'restriction_reason'])

        return {field: getattr(req, field) for field in REQUEST_FIELDS}


def publish_letter(user, letter_id, *, using='default'):
    """Approve an authored Letter for publication and finalize it.

    Invariant: The parent LetterRequest must be published.
    Transitions linked physical instance: is_public=True and status='waiting_print'.
    Returns the allowlisted card dictionary for the letter.
    """
    with transaction.atomic(using=using):
        _reviewer(user, using)
        letter = (
            Letter.objects.using(using)
            .select_for_update()
            .filter(pk=_identifier(letter_id))
            .first()
        )
        if letter is None:
            raise ValidationError('Letter not found.')

        if letter.request_id is not None:
            parent = (
                LetterRequest.objects.using(using)
                .select_for_update()
                .filter(pk=letter.request_id)
                .first()
            )
            if parent is None or not parent.is_published:
                raise ValidationError(
                    'A letter cannot be published while its originating request is unpublished.'
                )

        now = timezone.now()
        letter.is_published = True
        letter.automatically_restricted = False
        letter.restriction_reason = ''
        if letter.finalized_at is None:
            letter.finalized_at = now
        letter.save(
            update_fields=[
                'is_published',
                'automatically_restricted',
                'restriction_reason',
                'finalized_at',
            ]
        )

        # Mirror publication to physical instance and move to print queue
        copies = (
            LetterInstance.objects.using(using)
            .select_for_update()
            .filter(authored_letter_id=letter.pk)
        )
        for copy in copies:
            copy.is_public = True
            if copy.status == 'created':
                copy.status = 'waiting_print'
            copy.save(update_fields=['is_public', 'status'])

        return {field: getattr(letter, field) for field in LETTER_FIELDS}


def restrict_content(user, record_type, record_id, *, reason, using='default'):
    """Restrict and unpublish a request or letter with an internal reason.

    Hides the record from public/participants audience reads.
    If a letter is restricted, all linked physical copies are marked is_public=False.
    """
    if record_type not in ('request', 'letter'):
        raise ValidationError("record_type must be 'request' or 'letter'.")
    reason = _text(reason)

    with transaction.atomic(using=using):
        _reviewer(user, using)
        if record_type == 'request':
            req = (
                LetterRequest.objects.using(using)
                .select_for_update()
                .filter(pk=_identifier(record_id))
                .first()
            )
            if req is None:
                raise ValidationError('Request not found.')
            req.is_published = False
            req.automatically_restricted = True
            req.restriction_reason = reason
            req.save(
                update_fields=['is_published', 'automatically_restricted', 'restriction_reason']
            )
            return {field: getattr(req, field) for field in REQUEST_FIELDS}

        letter = (
            Letter.objects.using(using)
            .select_for_update()
            .filter(pk=_identifier(record_id))
            .first()
        )
        if letter is None:
            raise ValidationError('Letter not found.')
        letter.is_published = False
        letter.automatically_restricted = True
        letter.restriction_reason = reason
        letter.save(
            update_fields=['is_published', 'automatically_restricted', 'restriction_reason']
        )

        copies = (
            LetterInstance.objects.using(using)
            .select_for_update()
            .filter(authored_letter_id=letter.pk)
        )
        for copy in copies:
            copy.is_public = False
            copy.save(update_fields=['is_public'])

        return {field: getattr(letter, field) for field in LETTER_FIELDS}


def pending_review_requests(user, *, limit=20, using='default'):
    """Return allowlisted request cards awaiting moderation review."""
    with transaction.atomic(using=using):
        _reviewer(user, using)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError('The result limit must be an integer from 1 to 100.')
        qs = (
            LetterRequest.objects.using(using)
            .filter(is_published=False, automatically_restricted=True, restriction_reason='review_required')
            .order_by('-created_at', '-pk')
            .values(*REQUEST_FIELDS)[:limit]
        )
        return list(qs)


def pending_review_letters(user, *, limit=20, using='default'):
    """Return allowlisted letter cards awaiting moderation review."""
    with transaction.atomic(using=using):
        _reviewer(user, using)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError('The result limit must be an integer from 1 to 100.')
        qs = (
            Letter.objects.using(using)
            .filter(is_published=False, automatically_restricted=True, restriction_reason='review_required')
            .order_by('-created_at', '-pk')
            .values(*LETTER_FIELDS)[:limit]
        )
        return list(qs)
