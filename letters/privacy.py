"""Explicit public-route guards; private records remain available in admin.

These URL-boundary checks complement the existing list/read query filters.
They apply to every HTTP method and deliberately have no staff bypass.
"""
from functools import wraps

from django.shortcuts import get_object_or_404

from .models import LetterInstance, Stamp


def public_letter_required(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        get_object_or_404(LetterInstance, code=kwargs["code"], is_public=True)
        return view(request, *args, **kwargs)
    return guarded


def public_stamp_required(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        get_object_or_404(
            Stamp, number__iexact=kwargs["number"],
            is_active=True, letter__is_public=True,
        )
        return view(request, *args, **kwargs)
    return guarded
