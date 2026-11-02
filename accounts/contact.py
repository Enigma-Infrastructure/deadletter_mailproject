from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from .forms import EMAIL_HELP
from .models import User


class ContactForm(forms.Form):
    email = forms.EmailField(required=False, max_length=254, help_text=EMAIL_HELP)
    current_password = forms.CharField(widget=forms.PasswordInput, strip=False, label='Current password', help_text='Required to add, change, or remove your contact email.')


@sensitive_variables('current_password')
@transaction.atomic
def update_contact_email(*, actor, email, current_password):
    if not getattr(actor, 'is_authenticated', False):
        raise PermissionDenied
    account = User.objects.select_for_update().get(pk=actor.pk)
    if not account.is_active:
        raise PermissionDenied
    if not account.check_password(current_password):
        raise forms.ValidationError('Your current password was not accepted.')
    cleaned = forms.EmailField(required=False, max_length=254).clean(email)
    account.email = cleaned
    account.save(update_fields=['email', 'email_verified'])
    return account


@sensitive_post_parameters('current_password')
@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def contact(request):
    account = User.objects.get(pk=request.user.pk)
    form = ContactForm(request.POST if request.method == 'POST' else None, initial={'email': account.email})
    if request.method == 'POST' and form.is_valid():
        try:
            update_contact_email(actor=request.user, email=form.cleaned_data['email'], current_password=form.cleaned_data['current_password'])
        except forms.ValidationError as error:
            form.add_error('current_password', error)
        else:
            return redirect('account_contact')
    return render(request, 'registration/contact.html', {'form': form, 'contact_account': account})


@never_cache
@require_http_methods(['GET', 'POST'])
def recovery_unavailable(request, **kwargs):
    return render(request, 'registration/recovery_unavailable.html', status=503)
