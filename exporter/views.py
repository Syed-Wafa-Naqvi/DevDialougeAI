import logging
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from accounts.decorators import verification_required
from chat.models import Session
from exporter.archiver import ZipArchiver

logger = logging.getLogger('exporter')

@verification_required
def download_project_zip_api(request, session_id):
    import uuid
    is_uuid = False
    if isinstance(session_id, uuid.UUID):
        is_uuid = True
    else:
        try:
            uuid.UUID(str(session_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

    qs = Session.objects.prefetch_related('plans', 'messages', 'project_files', 'generated_codes')
    if is_uuid:
        session = get_object_or_404(qs, uuid=session_id, user=request.user)
    else:
        try:
            session = get_object_or_404(qs, id=int(session_id), user=request.user)
        except (ValueError, TypeError):
            raise Http404("Session not found")
    zip_bytes = ZipArchiver.create_project_zip(session)
    
    project_name = ZipArchiver.get_project_name(session)
    filename = f"{project_name}.zip"
    logger.info("[EXPORT ZIP] User %s downloaded project ZIP '%s' for Session #%s (%d bytes)", request.user, filename, session.id, len(zip_bytes))
    
    response = HttpResponse(zip_bytes, content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
