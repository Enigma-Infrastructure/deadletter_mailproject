# letters/serializers.py
from rest_framework import serializers

from people.models import Person
from .models import LetterConcept, LetterInstance


class PersonPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = [
            "id",
            "nickname",
            "social_place_name",
            "city",
            "region",
            "state",
            "write_about",
        ]


class LetterConceptSerializer(serializers.ModelSerializer):
    created_for = PersonPublicSerializer(read_only=True)

    class Meta:
        model = LetterConcept
        fields = [
            "id",
            "title",
            "description",
            "write_prompt",
            "destination_social_place_name",
            "destination_city",
            "destination_region",
            "destination_state",
            "created_for",
            "created_at",
        ]


class LetterInstanceSerializer(serializers.ModelSerializer):
    concept = LetterConceptSerializer(read_only=True)

    class Meta:
        model = LetterInstance
        fields = [
            "id",
            "code",
            "status",
            "is_public",
            "current_social_place_name",
            "current_city",
            "current_region",
            "current_state",
            "body_text",
            "concept",
            "created_at",
        ]
        read_only_fields = ["created_at"]
