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

@api_view(['POST'])
def place_order(request):
    data = request.data
    client = FyersClient()
    result = client.place_order(
        symbol=data.get("symbol"),
        qty=data.get("qty", 1),
        side=data.get("side", 1),
        type_=data.get("type", 2),
        product=data.get("product", "INTRADAY"),
        limit_price=data.get("limit_price", 0)
    )
    return Response(result)

@api_view(['GET'])
def get_positions(request):
    client = FyersClient()
    return Response(client.get_positions())
