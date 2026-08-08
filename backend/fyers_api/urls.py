from django.urls import path
from . import views

urlpatterns = [
    path('auth-url/', views.get_auth_url, name='fyers-auth-url'),
    path('callback/', views.fyers_callback, name='fyers-callback'),
    path('profile/', views.get_profile, name='fyers-profile'),
    path('quotes/', views.get_quotes, name='fyers-quotes'),
    path('place-order/', views.place_order, name='fyers-place-order'),
    path('positions/', views.get_positions, name='fyers-positions'),
]
