"""Durable creation wrappers; staged only, not HTTP endpoints.

Use one fresh UUID4 per intentional submission and reuse it for transport retries.
Returned full models are internal. Never log keys, payloads or receipt digests.
"""
import hashlib
import json
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.crypto import constant_time_compare, salted_hmac

from .domain_writes import _approved_actor, _identifier, _text, create_request, create_response
from .models import DomainSubmissionReceipt, Letter, LetterInstance, LetterRequest


class SubmissionConflict(Exception):
    pass


def _key_digest(key):
    try:
        parsed = UUID(key) if isinstance(key, str) else None
    except (ValueError, AttributeError):
        parsed = None
    if parsed is None or parsed.version != 4:
        raise ValidationError('A UUID4 submission key is required.')
    return hashlib.sha256(str(parsed).encode('ascii')).hexdigest()


def _payload_digest(operation, payload):
    encoded = json.dumps({'version': 1, 'operation': operation, 'payload': payload}, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return salted_hmac('letters.domain_submissions.v1', encoded, algorithm='sha256').hexdigest()


def _resolve(receipt, actor, using):
    if not receipt.completed:
        raise SubmissionConflict('The submission receipt is incomplete; review before retrying.')
    if receipt.operation == 'request':
        result = LetterRequest.objects.using(using).filter(pk=receipt.request_result_id, owner_id=actor.pk).first()
        if result is None:
            raise SubmissionConflict('The original submission is unavailable; it will not be recreated.')
        return result
    letter = Letter.objects.using(using).filter(pk=receipt.letter_result_id, writer_id=actor.pk).first()
    instance = LetterInstance.objects.using(using).filter(pk=receipt.instance_result_id, authored_letter_id=receipt.letter_result_id).first()
    if letter is None or instance is None:
        raise SubmissionConflict('The original submission is unavailable; it will not be recreated.')
    return letter, instance


def _submit(user, operation, key, payload, factory, using):
    key_digest = _key_digest(key)
    digest = _payload_digest(operation, payload)
    with transaction.atomic(using=using):
        actor = _approved_actor(user, using)
        receipt, created = DomainSubmissionReceipt.objects.using(using).get_or_create(
            actor_id=actor.pk, operation=operation, key_digest=key_digest,
            defaults={'payload_digest': digest},
        )
        if not constant_time_compare(receipt.payload_digest, digest):
            raise SubmissionConflict('This submission key was already used with different input.')
        if created:
            results = factory(actor)
            for field, value in results.items():
                setattr(receipt, field, value)
            receipt.completed = True
            receipt.save(using=using, update_fields=[*results, 'completed'])
        return _resolve(receipt, actor, using), not created


def submit_request(user, *, submission_key, recipient_id, prompt, requested_visibility=None, using='default'):
    payload = {'recipient_id': _identifier(recipient_id), 'prompt': _text(prompt), 'requested_visibility': requested_visibility}
    if requested_visibility not in (None, 'public', 'participants_only'):
        raise ValidationError('Unsupported requested audience.')
    def factory(actor):
        row = create_request(actor, using=using, **payload)
        return {'request_result_id': row.pk}
    return _submit(user, 'request', submission_key, payload, factory, using)


def submit_response(user, *, submission_key, request_id, body_text, requested_visibility=None, using='default'):
    payload = {'request_id': _identifier(request_id), 'body_text': _text(body_text), 'requested_visibility': requested_visibility}
    if requested_visibility not in (None, 'public', 'participants_only'):
        raise ValidationError('Unsupported requested audience.')
    def factory(actor):
        letter, instance = create_response(actor, using=using, **payload)
        return {'letter_result_id': letter.pk, 'instance_result_id': instance.pk}
    result, replayed = _submit(user, 'response', submission_key, payload, factory, using)
    return result[0], result[1], replayed
