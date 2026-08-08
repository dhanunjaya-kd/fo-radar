import json
import os
from django.http import JsonResponse
from fyers_apiv3 import fyersModel

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(BASE_DIR, "fyers_auth.json")

def get_fyers_client():
    if not os.path.exists(TOKEN_FILE):
        return None, "Token file not found. Run get_fyers_token.py first."
    
    with open(TOKEN_FILE, "r") as f:
        data = json.load(f)
    
    access_token = data.get("access_token")
    app_id = data.get("app_id", "LYNP1Z6GGG-100")
    
    if not access_token:
        return None, "Access token not found in token file."
    
    fyers = fyersModel.FyersModel(client_id=app_id, token=access_token, log_path="")
    return fyers, None

def fyers_profile(request):
    fyers, error = get_fyers_client()
    if error:
        return JsonResponse({"error": error}, status=400)
    
    response = fyers.get_profile()
    return JsonResponse(response)

def fyers_funds(request):
    fyers, error = get_fyers_client()
    if error:
        return JsonResponse({"error": error}, status=400)
    
    response = fyers.funds()
    return JsonResponse(response)

def fyers_holdings(request):
    fyers, error = get_fyers_client()
    if error:
        return JsonResponse({"error": error}, status=400)
    
    response = fyers.holdings()
    return JsonResponse(response)