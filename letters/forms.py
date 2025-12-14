from django import forms
from .models import LetterConcept

class ChooseConceptForm(forms.Form):
    concept = forms.ModelChoiceField(
        queryset=LetterConcept.objects.all(),
        label="Choose someone / concept to write for",
    )


class LetterBodyForm(forms.Form):
    body_text = forms.CharField(
        widget=forms.Textarea(attrs={"id": "id_body_text", "rows": 20}),
        label="Write your letter (Markdown)",
        help_text="Use Markdown for formatting; the editor below adds a toolbar and preview.",
    )