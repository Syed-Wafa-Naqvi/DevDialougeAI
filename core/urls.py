from django.urls import path
from core import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('features/', views.features_view, name='features'),
    path('pricing/', views.pricing_view, name='pricing'),
    path('about/', views.about_view, name='about'),
    path('signup/', views.signup_view, name='signup'),
    path('verify-otp/', views.verify_otp_view, name='verify_otp'),
    path('verify-otp/resend/', views.resend_otp_view, name='resend_otp'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password/', views.reset_password_view, name='reset_password'),
    path('settings/', views.settings_view, name='settings'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('new-chat/', views.new_chat_view, name='new_chat'),
    path('create-session/', views.create_session_view, name='create_session'),
    path('chat/<int:session_id>/', views.chat_view, name='chat'),
    path('chat/<int:session_id>/delete/', views.delete_session_view, name='delete_session'),
    path('chat/<int:session_id>/rename/', views.rename_session_api, name='rename_session'),
    
    # API endpoints
    path('api/chat/<int:session_id>/send/', views.send_message_api, name='send_message_api'),
    path('api/code/<int:code_id>/', views.get_code_file_api, name='get_code_file_api'),
]
