# letters/serializers.py
from rest_framework import serializers

from people.models import Person
from .models import LetterConcept, LetterInstance


class PersonPublicSerializer(serializers.ModelSerializer):
    pirate_address = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = [
            "id",
            "nickname",
            "pirate_address",
            "city",
            "write_about",
        ]

    def get_pirate_address(self, obj) -> str:
        return obj.pirate_address_display


class LetterConceptSerializer(serializers.ModelSerializer):
    created_for = PersonPublicSerializer(read_only=True)
    destination_place = serializers.SerializerMethodField()

    class Meta:
        model = LetterConcept
        fields = [
            "id",
            "title",
            "description",
            "write_prompt",
            "destination_place",
            "destination_city",
            "created_for",
            "created_at",
        ]

    def get_destination_place(self, obj) -> str:
        return obj.destination_display


class LetterInstanceSerializer(serializers.ModelSerializer):
    concept = LetterConceptSerializer(read_only=True)
    current_location = serializers.SerializerMethodField()
    stamp_numbers = serializers.SerializerMethodField()

    class Meta:
        model = LetterInstance
        fields = [
            "id",
            "code",
            "status",
            "is_public",
            "origin",
            "needs_printing",
            "current_location",
            "current_city",
            "body_text",
            "stamp_numbers",
            "concept",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_current_location(self, obj) -> str:
        return obj.current_location_display

    def get_stamp_numbers(self, obj) -> list:
        return list(
            obj.stamps.filter(is_active=True).values_list("number", flat=True)
        )
