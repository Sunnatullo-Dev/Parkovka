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
    path('api/history-report/', views.api_history_report, name='api_history_report'),
    path('api/export-csv/', views.api_export_csv, name='api_export_csv'),
    path('api/analytics-data/', views.api_analytics_data, name='api_analytics_data'),
    path('api/active-shift/', views.api_active_shift, name='api_active_shift'),
    path('api/close-shift/', views.api_close_shift, name='api_close_shift'),
    path('api/subscriptions/', views.api_subscriptions, name='api_subscriptions'),
    path('api/admin-login/', views.api_admin_login, name='api_admin_login'),
    path('api/admin-logout/', views.api_admin_logout, name='api_admin_logout'),
]
