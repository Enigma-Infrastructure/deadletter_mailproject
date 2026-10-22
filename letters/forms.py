from django import forms

class LetterBodyForm(forms.Form):
    body_text = forms.CharField(
        widget=forms.Textarea(attrs={"id": "id_body_text", "rows": 20}),
        label="Write your letter (Markdown)",
        help_text="Use Markdown for formatting; the editor below adds a toolbar and preview.",
    )


class ScanUpdateForm(forms.Form):
    """Validated form for the public scan/update endpoint."""

    kind = forms.CharField(
        max_length=20,
        label="What happened?",
    )
    note = forms.CharField(
        max_length=2000,
        required=False,
        label="Note (optional)",
    )
    place_name = forms.CharField(
        max_length=255,
        required=False,
        label="Where is it now?",
    )
    place_kind = forms.CharField(
        max_length=32,
        required=False,
        label="Kind of place",
    )
    city = forms.CharField(
        max_length=255,
        required=False,
        label="City",
    )
    photo = forms.ImageField(
        required=False,
        label="Photo (optional)",
        widget=forms.FileInput(attrs={"accept": "image/*"}),
    )
    instagram_handle = forms.CharField(
        max_length=100,
        required=False,
        label="Instagram handle (optional)",
    )

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo:
            # Validate file size (max 5 MB)
            if photo.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Photo must be 5 MB or less.")
            # Validate content type
            if photo.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
                raise forms.ValidationError("Photo must be JPEG, PNG, WebP, or GIF.")
        return photo