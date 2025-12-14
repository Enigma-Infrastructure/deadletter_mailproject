from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from .forms import AreaSearchForm
from letters.models import LetterInstance
from letters.serializers import LetterInstanceSerializer


def carry_home(request):
    form = AreaSearchForm(request.GET or None)
    letters = []

    if form.is_valid():
        city = form.cleaned_data.get("city")
        region = form.cleaned_data.get("region")
        state = form.cleaned_data.get("state")

        qs = LetterInstance.objects.filter(status__in=["waiting", "left"])
        if city:
            qs = qs.filter(current_city__iexact=city)
        if region:
            qs = qs.filter(current_region__iexact=region)
        if state:
            qs = qs.filter(current_state__iexact=state)

        letters = qs.select_related("concept", "recipient")[:100]

    return render(request, "carry_home.html", {"form": form, "letters": letters})


class LettersInMyAreaAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        city = request.query_params.get("city")
        region = request.query_params.get("region")
        state = request.query_params.get("state")

        qs = LetterInstance.objects.filter(status__in=["waiting", "left"])
        if city:
            qs = qs.filter(current_city__iexact=city)
        if region:
            qs = qs.filter(current_region__iexact=region)
        if state:
            qs = qs.filter(current_state__iexact=state)

        serializer = LetterInstanceSerializer(qs[:100], many=True)
        return Response(serializer.data)
