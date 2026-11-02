from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import RegistrationSource, User

VISIBILITY_HELP = ('Public: Anyone on the internet, including search engines and automated scrapers or AI systems, can read it. Copies may remain after visibility changes. Participants only: Approved participants and organizers can read it and may copy or share it. This is not confidential or end-to-end encrypted.')

class RegistrationForm(UserCreationForm):
    source = forms.SlugField(max_length=64, required=False, label='Event source code')

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'default_request_visibility', 'default_body_visibility')
        help_texts = {name: VISIBILITY_HELP for name in ('default_request_visibility', 'default_body_visibility')}

    def clean_source(self):
        code = self.cleaned_data['source']
        self.registration_source = None
        if code:
            source = RegistrationSource.objects.filter(code=code).first()
            if source is None or not source.is_available():
                raise forms.ValidationError('Invalid, inactive, or expired source code. Remove it to register without a source.')
            self.registration_source = source
        return code

    def save(self, commit=True):
        user = super().save(commit=False)
        user.participant_status = 'pending'
        user.is_staff = user.is_superuser = user.is_collaborator = False
        user.registration_source = self.registration_source
        user.participant_reviewed_by = None
        user.participant_reviewed_at = None
        if commit:
            user.save()
        return user

class PreferencesForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('default_request_visibility', 'default_body_visibility')
        help_texts = {name: VISIBILITY_HELP for name in ('default_request_visibility', 'default_body_visibility')}

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save(update_fields=list(self.Meta.fields))
        return user
