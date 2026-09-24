from django.urls import path
from exporter import views

urlpatterns = [
    path('api/session/<int:session_id>/download/', views.download_project_zip_api, name='download_project_zip_api'),
]
