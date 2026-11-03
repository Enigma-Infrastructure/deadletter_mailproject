"""Staged field allowlists, not HTML sanitization or live route integration.

Pass the server-authenticated user. Audience and draft workspaces are distinct.
These dictionaries intentionally never include addresses, relations or codes.
"""
from django.core.exceptions import ValidationError

from .domain_access import readable_letters, readable_requests
from .domain_drafts import authored_letter_drafts, owned_request_drafts


REQUEST_FIELDS = ('id', 'prompt', 'recipient_alias')
LETTER_FIELDS = ('id', 'body_text', 'recipient_alias')


def _detail(queryset, identifier, fields):
    if type(identifier) is not int or identifier <= 0:
        return None
    return queryset.filter(pk=identifier).values(*fields).first()


def _list(queryset, limit, fields):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError('The result limit must be an integer from 1 to 100.')
    return list(queryset.order_by('-created_at', '-pk').values(*fields)[:limit])


def request_card(user, request_id, using='default'):
    return _detail(readable_requests(user, using), request_id, REQUEST_FIELDS)


def letter_card(user, letter_id, using='default'):
    return _detail(readable_letters(user, using), letter_id, LETTER_FIELDS)


def request_cards(user, *, limit=20, using='default'):
    return _list(readable_requests(user, using), limit, REQUEST_FIELDS)


def letter_cards(user, *, limit=20, using='default'):
    return _list(readable_letters(user, using), limit, LETTER_FIELDS)


def request_draft_card(user, request_id, using='default'):
    return _detail(owned_request_drafts(user, using), request_id, REQUEST_FIELDS)


def letter_draft_card(user, letter_id, using='default'):
    return _detail(authored_letter_drafts(user, using), letter_id, LETTER_FIELDS)
