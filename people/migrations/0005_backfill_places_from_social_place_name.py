# Generated data migration: backfill Place objects from legacy
# free-text social_place_name values on Person, and link people to them.
from django.db import migrations


def backfill_places(apps, schema_editor):
    Person = apps.get_model("people", "Person")
    Place = apps.get_model("people", "Place")

    for person in Person.objects.exclude(social_place_name="").exclude(
        social_place_name__isnull=True
    ):
        place, _created = Place.objects.get_or_create(
            name=person.social_place_name.strip(),
            city=person.city or "",
            defaults={"kind": "other"},
        )
        if person.pirate_place_id is None:
            person.pirate_place = place
            person.save(update_fields=["pirate_place"])


def unbackfill_places(apps, schema_editor):
    # Reverse: copy place name back to free text and clear the link.
    Person = apps.get_model("people", "Person")
    for person in Person.objects.select_related("pirate_place").exclude(
        pirate_place__isnull=True
    ):
        person.social_place_name = person.pirate_place.name
        person.pirate_place = None
        person.save(update_fields=["social_place_name", "pirate_place"])


class Migration(migrations.Migration):

    dependencies = [
        ("people", "0004_alter_person_social_place_name_place_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_places, unbackfill_places),
    ]
