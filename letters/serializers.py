# letters/serializers.py
from rest_framework import serializers

from people.models import LetterRequest
from .models import LetterInstance


class LetterRequestPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = LetterRequest
        fields = [
            "id",
            "nickname",
            "pirate_address",
            "city",
            "state",
            "region",
            "write_about",
        ]


class LetterInstanceSerializer(serializers.ModelSerializer):
    request = LetterRequestPublicSerializer(read_only=True)

    # Derive current location from the most recent hop
    current_city   = serializers.SerializerMethodField()
    current_region = serializers.SerializerMethodField()

    class Meta:
        model = LetterInstance
        fields = [
            "id",
            "code",
            "is_public",
            "body_text",
            "request",
            "current_city",
            "current_region",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_current_city(self, obj):
        hop = obj.hops.order_by("-created_at").first()
        return hop.city if hop else ""

    def get_current_region(self, obj):
        hop = obj.hops.order_by("-created_at").first()
        return hop.region if hop else ""
