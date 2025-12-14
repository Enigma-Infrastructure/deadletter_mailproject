from django import forms
from .models import Person
from letters.models import LetterConcept


class RecipientSignupForm(forms.Form):
    nickname = forms.CharField(max_length=255, label="Name or nickname")

    social_place_name = forms.CharField(
        max_length=255,
        required=False,
        label="Place where people can find you",
        help_text="e.g. a bar, camp, venue, event space.",
    )

    city = forms.CharField(max_length=255, required=False)
    region = forms.CharField(max_length=255, required=False)
    state = forms.CharField(max_length=255, required=False)

    write_about = forms.CharField(
        widget=forms.Textarea,
        required=False,
        label="Topic / what to write about",
    )

    def save(self, user=None):
        data = self.cleaned_data
        person = Person.objects.create(
            nickname=data["nickname"],
            social_place_name=data.get("social_place_name", ""),
            city=data.get("city", ""),
            region=data.get("region", ""),
            state=data.get("state", ""),
            write_about=data.get("write_about", ""),
            created_by=user if user and user.is_authenticated else None,
        )

        concept = LetterConcept.objects.create(
            title=f"Letter for {person.nickname}",
            description="A letter concept created for this person.",
            write_prompt=person.write_about,
            destination_social_place_name=person.social_place_name,
            destination_city=person.city,
            destination_region=person.region,
            destination_state=person.state,
            created_for=person,
            created_by=user if user and user.is_authenticated else None,
        )

        return person, concept
