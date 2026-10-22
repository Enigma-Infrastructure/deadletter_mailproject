# accounts/views.py
from django.shortcuts import render

from .models import ReputationEvent


def leaderboard(request):
    """
    Public reputation leaderboard: top couriers by reputation earned
    through reactive stamp scans (pickups, deliveries, photos...).
    """
    return render(
        request,
        "leaderboard.html",
        {
            "leaders": ReputationEvent.leaderboard(limit=25),
        },
    )
