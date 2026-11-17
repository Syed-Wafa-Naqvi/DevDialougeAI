import json
import logging
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from core.self_healing import SelfHealingEngine, render_self_healing_response

logger = logging.getLogger('core.views')


def self_healing_status_api(request):
    """
    Returns the real-time operational and remediation status of the self-healing engine.
    Called by the client-side maintenance page and chat interface to poll progress.
    """
    status_data = SelfHealingEngine.get_status()
    return JsonResponse(status_data, status=200)


def self_healing_health_api(request):
    """
    Lightweight health check endpoint.
    Returns 200 OK when operational, or 503 if currently actively undergoing hot-patching.
    """
    is_active = SelfHealingEngine.is_healing_active()
    status_code = 503 if is_active else 200
    return JsonResponse({
        "status": "healing" if is_active else "ok",
        "healing_active": is_active,
        "details": SelfHealingEngine.get_status()
    }, status=status_code)


@csrf_exempt
def self_healing_trigger_api(request):
    """
    Administrative and testing endpoint to trigger an autonomous self-healing cycle.
    Restricted to superusers, staff, or test suites.
    """
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed. Use POST."}, status=405)

    if not (getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False) or settings.DEBUG or 'test' in settings.SETTINGS_MODULE):
        return JsonResponse({"error": "Unauthorized. Staff privileges required."}, status=403)

    try:
        data = json.loads(request.body.decode('utf-8')) if request.body else {}
    except Exception:
        data = {}

    simulated_err = data.get("error", "Simulated unhandled system exception")
    simulated_file = data.get("file", "chat/views.py")
    simulated_line = int(data.get("line", 10))

    class SimulatedSystemError(RuntimeError):
        pass

    exc = SimulatedSystemError(simulated_err)
    incident_data = SelfHealingEngine.trigger_healing(
        exc,
        request=request,
        target_file=simulated_file,
        offending_line=simulated_line,
        run_async=data.get("run_async", True)
    )

    return JsonResponse({
        "status": "triggered",
        "message": "Autonomous self-healing triggered successfully.",
        "incident": incident_data
    }, status=200)


def custom_500_view(request):
    """
    Custom 500 error handler invoked by Django's URL routing when an uncaught exception
    escapes view processing.
    """
    logger.error("[500 HANDLER HIT] Intercepted 500 on path: %s", request.path)
    exc = Exception(f"Unhandled 500 Internal Error on {request.path}")
    incident_data = SelfHealingEngine.trigger_healing(exc, request=request, run_async=True)
    return render_self_healing_response(request, incident_data=incident_data, status_code=500)
