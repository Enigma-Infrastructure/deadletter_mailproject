"""Explicit historical conversion; legacy workflows remain authoritative."""
from django.db import transaction

from .models import Letter, LetterConcept, LetterInstance, LetterRequest


class BackfillConflict(Exception):
    pass


def snapshots(person, concept):
    # A concept's recorded destination wins, even when incomplete. Never use current_place.
    place = concept.destination_place if concept else (person.pirate_place if person else None)
    city = place.city if place else (concept.destination_city if concept else (person.city if person else ''))
    name = place.name if place else ''
    return {
        'recipient_id': person.pk if person else None,
        'recipient_alias': person.nickname if person else '',
        'destination_place_id': place.pk if place else None,
        'destination_city': city,
        'destination_label': name.strip() + (f' · {city}' if city else ''),
    }


def backfill_sources(using='default', apply=False):
    # Stop all source and target writers. Locks protect rows, not new inserts or schema changes.
    with transaction.atomic(using=using):
        concept_rows = LetterConcept.objects.using(using).order_by('pk')
        instance_rows = LetterInstance.objects.using(using).order_by('pk')
        if apply:
            concept_rows = concept_rows.select_for_update()
            instance_rows = instance_rows.select_for_update()
        concepts = {row.pk: row for row in concept_rows}
        instances = list(instance_rows)
        requests = {row.legacy_source_id: row for row in LetterRequest.objects.using(using).exclude(legacy_source_id=None)}
        eligible = [row for row in concepts.values() if row.created_for_id is not None]
        pending = [row for row in instances if row.authored_letter_id is None]
        for instance in pending:
            concept = concepts.get(instance.concept_id)
            if concept and concept.created_for_id and instance.recipient_id != concept.created_for_id:
                raise BackfillConflict('Unlinked instances have missing or conflicting concept recipients. Review sources before applying; no conversion was committed.')
        report = {
            'schema_version': 1,
            'requests_to_create': sum(row.pk not in requests for row in eligible),
            'letters_to_create': len(pending),
            'instances_to_link': len(pending),
            'existing_requests_preserved': sum(row.pk in requests for row in eligible),
            'existing_instance_links_preserved': len(instances) - len(pending),
            'concepts_without_recipient_skipped': len(concepts) - len(eligible),
            'requests_created': 0,
            'letters_created': 0,
            'instances_linked': 0,
        }
        if not apply:
            return report
        for concept in eligible:
            if concept.pk in requests:
                continue
            request = LetterRequest.objects.using(using).create(
                legacy_source_id=concept.pk,
                prompt=concept.write_prompt,
                **snapshots(concept.created_for, concept),
            )
            LetterRequest.objects.using(using).filter(pk=request.pk).update(created_at=concept.created_at)
            requests[concept.pk] = request
            report['requests_created'] += 1
        for instance in pending:
            concept = concepts.get(instance.concept_id)
            request = requests.get(concept.pk) if concept and concept.created_for_id else None
            letter = Letter.objects.using(using).create(
                request_id=request.pk if request else None,
                body_text=instance.body_text,
                prompt_snapshot=concept.write_prompt if concept else '',
                automatically_restricted=not instance.is_public,
                restriction_reason='legacy_hidden' if not instance.is_public else '',
                **snapshots(instance.recipient, concept),
            )
            Letter.objects.using(using).filter(pk=letter.pk).update(created_at=instance.created_at)
            changed = LetterInstance.objects.using(using).filter(pk=instance.pk, authored_letter_id=None).update(authored_letter_id=letter.pk)
            if changed != 1:
                raise BackfillConflict('An instance link changed during conversion. No conversion was committed; stop writers and review before retrying.')
            report['letters_created'] += 1
            report['instances_linked'] += 1
        return report
