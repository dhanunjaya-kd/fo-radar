from django.urls import path
from . import views

urlpatterns = [
    path('', views.news_list, name='news-list'),
    path('fetch/', views.fetch_news, name='fetch-news'),
]
