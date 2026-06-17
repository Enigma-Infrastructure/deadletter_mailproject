from django import forms


class LetterBodyForm(forms.Form):
    body_text = forms.CharField(
        widget=forms.Textarea(attrs={"id": "id_body_text", "rows": 20}),
        label="Write your letter (Markdown)",
        help_text="Use Markdown for formatting; the editor below adds a toolbar and preview.",
    )
