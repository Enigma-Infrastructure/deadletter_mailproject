"""Aggregate-only source inventory. Never infer ownership or classify content."""
from django.db import transaction
from django.db.models import Count, F

from accounts.models import ReputationEvent
from media_app.models import MediaItem
from .models import Letter, LetterConcept, LetterHop, LetterInstance, LetterRequest, Stamp, StampUpdate


def collect_audit(using='default'):
    # atomic groups reads; stop writers for a reliable cross-backend inventory.
    with transaction.atomic(using=using):
        concepts = LetterConcept.objects.using(using).all()
        instances = LetterInstance.objects.using(using).all()
        requests = LetterRequest.objects.using(using).all()
        letters = Letter.objects.using(using).all()
        sizes = concepts.annotate(copy_count=Count('instances', distinct=True))
        linked = instances.filter(authored_letter_id__isnull=False)
        comparable = instances.filter(concept__created_for_id__isnull=False, recipient_id__isnull=False)
        published_requests = requests.filter(is_published=True)
        published_letters = letters.filter(is_published=True)
        report = {
            'schema_version': 1,
            'legacy_concepts': {
                'total': concepts.count(),
                'with_recipient': concepts.filter(created_for_id__isnull=False).count(),
                'without_recipient': concepts.filter(created_for_id__isnull=True).count(),
                'with_no_instances': sizes.filter(copy_count=0).count(),
                'with_one_instance': sizes.filter(copy_count=1).count(),
                'with_multiple_instances': sizes.filter(copy_count__gt=1).count(),
                'with_multiple_instance_recipients': concepts.annotate(recipient_count=Count('instances__recipient_id', distinct=True)).filter(recipient_count__gt=1).count(),
                'with_destination_place': concepts.filter(destination_place_id__isnull=False).count(),
                'with_nonempty_prompt': concepts.exclude(write_prompt='').count(),
                'already_mapped_to_request': concepts.filter(migrated_request__isnull=False).count(),
            },
            'physical_instances': {
                'total': instances.count(),
                'without_concept': instances.filter(concept_id__isnull=True).count(),
                'without_recipient': instances.filter(recipient_id__isnull=True).count(),
                'with_nonempty_legacy_body': instances.exclude(body_text='').count(),
                'legacy_public_flag_true': instances.filter(is_public=True).count(),
                'legacy_public_flag_false': instances.filter(is_public=False).count(),
                'with_printed_timestamp': instances.filter(printed_at__isnull=False).count(),
                'marked_needs_printing': instances.filter(needs_printing=True).count(),
                'printed_but_marked_needs_printing': instances.filter(printed_at__isnull=False, needs_printing=True).count(),
                'with_authored_letter': linked.count(),
                'without_authored_letter': instances.filter(authored_letter_id__isnull=True).count(),
                'recipient_disagrees_with_concept': comparable.exclude(recipient_id=F('concept__created_for_id')).count(),
                'concept_has_recipient_but_instance_does_not': instances.filter(concept__created_for_id__isnull=False, recipient_id__isnull=True).count(),
                'linked_legacy_body_differs_from_authored_body': linked.exclude(body_text=F('authored_letter__body_text')).count(),
            },
            'new_requests': {
                'total': requests.count(),
                'with_legacy_source': requests.filter(legacy_source_id__isnull=False).count(),
                'with_owner': requests.filter(owner_id__isnull=False).count(),
                'with_submitter': requests.filter(submitted_by_id__isnull=False).count(),
                'published': published_requests.count(),
                'requested_public': requests.filter(requested_visibility='public').count(),
                'automatically_restricted': requests.filter(automatically_restricted=True).count(),
                'open': requests.filter(is_open=True).count(),
                'without_recipient_alias_snapshot': requests.filter(recipient_alias='').count(),
                'without_destination_label_snapshot': requests.filter(destination_label='').count(),
            },
            'authored_letters': {
                'total': letters.count(),
                'without_request': letters.filter(request_id__isnull=True).count(),
                'with_writer': letters.filter(writer_id__isnull=False).count(),
                'published': published_letters.count(),
                'requested_public': letters.filter(requested_visibility='public').count(),
                'automatically_restricted': letters.filter(automatically_restricted=True).count(),
                'finalized': letters.filter(finalized_at__isnull=False).count(),
                'without_instances': letters.filter(instances__isnull=True).count(),
                'with_multiple_instances': letters.annotate(copy_count=Count('instances', distinct=True)).filter(copy_count__gt=1).count(),
                'without_recipient_alias_snapshot': letters.filter(recipient_alias='').count(),
                'without_destination_label_snapshot': letters.filter(destination_label='').count(),
            },
            'physical_history': {
                'stamps': Stamp.objects.using(using).count(),
                'active_stamps': Stamp.objects.using(using).filter(is_active=True).count(),
                'instances_with_multiple_active_stamps': instances.annotate(active_count=Count('stamps', filter=__import__('django.db.models', fromlist=['Q']).Q(stamps__is_active=True), distinct=True)).filter(active_count__gt=1).count(),
                'stamp_updates': StampUpdate.objects.using(using).count(),
                'hops': LetterHop.objects.using(using).count(),
                'media_records': MediaItem.objects.using(using).count(),
                'reputation_events': ReputationEvent.objects.using(using).count(),
            },
        }
        return report
