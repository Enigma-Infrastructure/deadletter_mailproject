# routing/views.py
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from .forms import AreaSearchForm
from letters.models import LetterInstance, LetterHop
from letters.serializers import LetterInstanceSerializer


def carry_home(request):
    """
    Shows letters currently waiting to be carried in a given area.
    Filters on LetterHop.city / region / state.
    """
    form = AreaSearchForm(request.GET or None)
    letters = []

    if form.is_valid():
        city   = form.cleaned_data.get("city")   or ""
        region = form.cleaned_data.get("region") or ""
        state  = form.cleaned_data.get("state")  or ""

        qs = LetterInstance.objects.filter(
            is_public=True,
            hops__status="waiting",
        ).select_related("request").distinct()

        if city:
            qs = qs.filter(hops__city__iexact=city)
        if region:
            qs = qs.filter(hops__region__iexact=region)

        letters = qs[:100]

    return render(request, "carry_home.html", {"form": form, "letters": letters})


class LettersInMyAreaAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        city   = request.query_params.get("city",   "")
        region = request.query_params.get("region", "")

        qs = LetterInstance.objects.filter(
            is_public=True,
            hops__status="waiting",
        ).distinct()

        if city:
            qs = qs.filter(hops__city__iexact=city)
        if region:
            qs = qs.filter(hops__region__iexact=region)

        serializer = LetterInstanceSerializer(qs[:100], many=True)
        return Response(serializer.data)
