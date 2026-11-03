"""Staged optimistic state checks, not revision history or HTTP endpoints."""
import json

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils.crypto import constant_time_compare, salted_hmac

from .domain_drafts import edit_letter_draft, edit_request_draft
from .domain_presentation import LETTER_FIELDS, REQUEST_FIELDS
from .domain_writes import _approved_actor, _identifier
from .models import Letter, LetterInstance, LetterRequest


TOKEN_SALT = 'letters.draft_state.v1'
TOKEN_MAX_AGE = 1800


class DraftConflict(Exception):
    pass


def _fields(row):
    return {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}


def _context(actor, kind, identifier, using):
    model, owner_field = (LetterRequest, 'owner_id') if kind == 'request' else (Letter, 'writer_id')
    row = model.objects.using(using).select_for_update().filter(pk=_identifier(identifier), is_published=False, **{owner_field: actor.pk}).first()
    if row is None:
        raise PermissionDenied('This draft is unavailable.')
    state = {'record': _fields(row)}
    if kind == 'letter':
        copies = LetterInstance.objects.using(using).select_for_update().filter(authored_letter_id=row.pk).order_by('pk')
        state['instances'] = [_fields(copy) for copy in copies]
    else:
        state['response_count'] = Letter.objects.using(using).filter(request_id=row.pk).count()
    encoded = json.dumps(state, cls=DjangoJSONEncoder, sort_keys=True, separators=(',', ':'))
    digest = salted_hmac(TOKEN_SALT, encoded, algorithm='sha256').hexdigest()
    return row, {'v': 1, 'kind': kind, 'id': row.pk, 'actor': actor.pk, 'database': using, 'digest': digest}


def _envelope(row, payload, kind):
    fields = REQUEST_FIELDS if kind == 'request' else LETTER_FIELDS
    return {'card': {field: getattr(row, field) for field in fields}, 'edit_token': signing.dumps(payload, salt=TOKEN_SALT)}


def _verify(token, current):
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError
        expected = signing.loads(token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
        if not isinstance(expected, dict) or set(expected) != set(current):
            raise ValueError
        for key in ('v', 'kind', 'id', 'actor', 'database'):
            if expected[key] != current[key]:
                raise ValueError
        if not isinstance(expected['digest'], str) or not constant_time_compare(expected['digest'], current['digest']):
            raise ValueError
    except (signing.BadSignature, ValueError, TypeError):
        raise DraftConflict('The draft state is stale or the edit token is invalid/expired. Reload before saving.') from None


def _snapshot(user, kind, identifier, using):
    with transaction.atomic(using=using):
        actor = _approved_actor(user, using)
        row, payload = _context(actor, kind, identifier, using)
        return _envelope(row, payload, kind)


def request_draft_snapshot(user, request_id, using='default'):
    return _snapshot(user, 'request', request_id, using)


def letter_draft_snapshot(user, letter_id, using='default'):
    return _snapshot(user, 'letter', letter_id, using)


def save_request_draft(user, *, request_id, expected_token, prompt, requested_visibility=None, using='default'):
    with transaction.atomic(using=using):
        actor = _approved_actor(user, using)
        _, current = _context(actor, 'request', request_id, using)
        _verify(expected_token, current)
        edit_request_draft(actor, request_id=request_id, prompt=prompt, requested_visibility=requested_visibility, using=using)
        row, payload = _context(actor, 'request', request_id, using)
        return _envelope(row, payload, 'request')


def save_letter_draft(user, *, letter_id, expected_token, body_text, requested_visibility=None, using='default'):
    with transaction.atomic(using=using):
        actor = _approved_actor(user, using)
        _, current = _context(actor, 'letter', letter_id, using)
        _verify(expected_token, current)
        edit_letter_draft(actor, letter_id=letter_id, body_text=body_text, requested_visibility=requested_visibility, using=using)
        row, payload = _context(actor, 'letter', letter_id, using)
        return _envelope(row, payload, 'letter')
