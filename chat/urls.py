from django.urls import path
from chat import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('features/', views.features_view, name='features'),
    path('pricing/', views.pricing_view, name='pricing'),
    path('about/', views.about_view, name='about'),
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
