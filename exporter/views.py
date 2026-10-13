from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from accounts.decorators import verification_required
from chat.models import Session
from exporter.archiver import ZipArchiver

@verification_required
def download_project_zip_api(request, session_id):
    session = get_object_or_404(Session, id=session_id, user=request.user)
    zip_bytes = ZipArchiver.create_project_zip(session)
    
    project_name = ZipArchiver.get_project_name(session)
    filename = f"{project_name}.zip"
    
    response = HttpResponse(zip_bytes, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
