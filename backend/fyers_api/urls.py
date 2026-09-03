from django.urls import path
from . import views

urlpatterns = [
    path('auth-url/', views.get_auth_url, name='fyers-auth-url'),
    path('callback/', views.fyers_callback, name='fyers-callback'),
    path('profile/', views.get_profile, name='fyers-profile'),
    path('quotes/', views.get_quotes, name='fyers-quotes'),
    # Sep 3 2026: place-order/ removed -- see the matching comment in
    # views.py. Nothing called it; removing beats gating an unused,
    # real-money-capable endpoint.
    path('positions/', views.get_positions, name='fyers-positions'),
]
