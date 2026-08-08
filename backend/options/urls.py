from django.urls import path
from . import views

urlpatterns = [
    path('chain/<str:symbol>/', views.option_chain, name='option-chain'),
    path('dive/<str:symbol>/', views.options_dive, name='options-dive'),
]
