"""Staged write services, intentionally not wired to routes.

Call only with the server-authenticated user. Each successful call creates a
new submission: no replay/idempotency guarantee. Returned models are private.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from people.models import Person, Place
from .access_policy import ContentAccess, Viewer, can_read_request
from .models import Letter, LetterInstance, LetterRequest


def _approved_actor(user, using):
    if user is None or not getattr(user, 'is_authenticated', False) or user.pk is None:
        raise PermissionDenied('Active approved participation is required.')
    actor = get_user_model().objects.using(using).select_for_update().filter(pk=user.pk).first()
    if actor is None or not actor.is_active or actor.participant_status != 'approved':
        raise PermissionDenied('Active approved participation is required.')
    return actor


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError('Nonblank text is required.')
    return value


def _visibility(value, default):
    value = default if value is None else value
    if value not in ('public', 'participants_only'):
        raise ValidationError('Unsupported requested audience.')
    return value


def _identifier(value):
    if type(value) is not int or value <= 0:
        raise ValidationError('A positive integer record identifier is required.')
    return value


def create_request(user, *, recipient_id, prompt, requested_visibility=None, using='default'):
    """Actor owns this submission, not the selected Person's identity."""
    with transaction.atomic(using=using):
        actor = _approved_actor(user, using)
        prompt = _text(prompt)
        visibility = _visibility(requested_visibility, actor.default_request_visibility)
        person = Person.objects.using(using).select_for_update().filter(pk=_identifier(recipient_id), is_active=True).first()
        if person is None:
            raise ValidationError('An active recipient is required.')
        place = None
        if person.pirate_place_id is not None:
            place = Place.objects.using(using).select_for_update().filter(pk=person.pirate_place_id, is_active=True).first()
            if place is None:
                raise ValidationError('The recipient destination is unavailable.')
        city = place.city if place else person.city
        label = (place.name.strip() if place else '') + (f' · {city}' if city else '')
        return LetterRequest.objects.using(using).create(
            prompt=prompt, recipient_id=person.pk, recipient_alias=person.nickname,
            destination_place_id=place.pk if place else None, destination_city=city, destination_label=label,
            owner_id=actor.pk, submitted_by_id=actor.pk, requested_visibility=visibility,
            automatically_restricted=True, restriction_reason='review_required', is_published=False,
        )


def create_response(user, *, request_id, body_text, requested_visibility=None, using='default'):
    """Create a new authored draft and hidden physical instance together."""
    with transaction.atomic(using=using):
        actor = _approved_actor(user, using)
        body_text = _text(body_text)
        visibility = _visibility(requested_visibility, actor.default_body_visibility)
        parent = LetterRequest.objects.using(using).select_for_update().filter(pk=_identifier(request_id)).first()
        if parent is None or not parent.is_open or not can_read_request(
            Viewer(True, actor.is_active, actor.participant_status),
            ContentAccess(parent.requested_visibility, parent.automatically_restricted, parent.is_published),
        ):
            raise PermissionDenied('The request is not available for responses.')
        letter = Letter.objects.using(using).create(
            request_id=parent.pk, concept_id=parent.concept_id, writer_id=actor.pk, body_text=body_text,
            prompt_snapshot=parent.prompt, recipient_id=parent.recipient_id, recipient_alias=parent.recipient_alias,
            destination_place_id=parent.destination_place_id, destination_city=parent.destination_city,
            destination_label=parent.destination_label, requested_visibility=visibility,
            automatically_restricted=True, restriction_reason='review_required', is_published=False,
        )
        instance = LetterInstance.objects.using(using).create(
            authored_letter_id=letter.pk, recipient_id=parent.recipient_id, body_text=body_text,
            created_by_id=actor.pk, current_place_id=parent.destination_place_id, current_city=parent.destination_city,
            status='created', origin='online', needs_printing=True, is_public=False,
        )
        return letter, instance
