from django.urls import path
from parking import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('api/spots/', views.api_spots, name='api_spots'),
    path('api/active-sessions/', views.api_active_sessions, name='api_active_sessions'),
    path('api/start-session/', views.api_start_session, name='api_start_session'),
    path('api/calculate-fee/', views.api_calculate_fee, name='api_calculate_fee'),
    path('api/end-session/', views.api_end_session, name='api_end_session'),
    path('api/today-report/', views.api_today_report, name='api_today_report'),
    path('api/update-rate/', views.api_update_rate, name='api_update_rate'),
]
