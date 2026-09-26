from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.ResearchSearchView.as_view(), name='research_search'),
    path('company/<str:symbol>/', views.CompanyView.as_view(), name='research_company'),
    path('company/<str:symbol>/financials/', views.CompanyFinancialsView.as_view(), name='research_financials'),
    path('company/<str:symbol>/valuation/', views.CompanyValuationView.as_view(), name='research_valuation'),
    path('company/<str:symbol>/ownership/', views.CompanyOwnershipView.as_view(), name='research_ownership'),
    path('company/<str:symbol>/news/', views.CompanyNewsView.as_view(), name='research_news'),
    path('company/<str:symbol>/report/', views.CompanyReportView.as_view(), name='research_report'),
    path('company/<str:symbol>/history/', views.CompanyHistoryView.as_view(), name='research_history'),
    path('company/<str:symbol>/refresh/', views.CompanyRefreshView.as_view(), name='research_refresh'),
    path('company/<str:symbol>/chat/', views.CompanyChatView.as_view(), name='research_chat'),
    path('company/<str:symbol>/technical/', views.CompanyTechnicalView.as_view(), name='research_technical'),
    path('company/<str:symbol>/averaging/', views.CompanyAveragingView.as_view(), name='research_averaging'),
]
