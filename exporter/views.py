from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from accounts.decorators import verification_required
from chat.models import Session
from exporter.archiver import ZipArchiver

@verification_required
def download_project_zip_api(request, session_id):
    session = get_object_or_404(Session, id=session_id, user=request.user)
    zip_bytes = ZipArchiver.create_project_zip(session)
    
    clean_title = "".join([c if c.isalnum() else "_" for c in session.title]).strip("_") or "Project"
    filename = f"DevDialogue_{clean_title}.zip"
    
    response = HttpResponse(zip_bytes, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
