from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.conf import settings
from .auth import FyersAuth
from .client import FyersClient

@api_view(['GET'])
def get_auth_url(request):
    auth = FyersAuth()
    return Response({"auth_url": auth.generate_auth_url()})

@api_view(['GET'])
def fyers_callback(request):
    auth_code = request.GET.get("auth_code")
    if not auth_code:
        return Response({"error": "No auth code"}, status=400)
    auth = FyersAuth()
    token = auth.generate_access_token(auth_code)
    if token:
        return Response({"access_token": token, "status": "success"})
    return Response({"error": "Token generation failed"}, status=400)

@api_view(['GET'])
def get_profile(request):
    client = FyersClient()
    return Response(client.get_profile())

@api_view(['GET'])
def get_quotes(request):
    symbols = request.GET.get("symbols", "").split(",")
    client = FyersClient()
    return Response(client.get_quotes(symbols))

# Sep 3 2026: place_order removed entirely -- confirmed via a full grep
# across both the frontend and the rest of the backend that nothing
# anywhere called this endpoint. It exposed a live, unauthenticated
# order-placement path (real money on a real Fyers account) with zero
# actual feature depending on it. Removing beats gating: no auth logic
# to get right, no risk of forgetting to update it later, and no
# feature loss since nothing used it. If real one-click execution from
# a signal becomes an actual feature later, this needs to come back
# WITH a real auth gate from day one, not bolted on after.

@api_view(['GET'])
def get_positions(request):
    client = FyersClient()
    return Response(client.get_positions())
