import json
import logging
import os
import threading
import time
import zoneinfo
from django.utils import timezone

logger = logging.getLogger('core.middleware')

class TimezoneMiddleware:
    """
    Activates the client's preferred timezone for the duration of the HTTP request,
    and reliably deactivates it in a finally block to prevent thread-local leakage
    between users in multi-threaded application servers.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tzname = request.COOKIES.get('django_timezone')
        activated = False
        if tzname:
            try:
                timezone.activate(zoneinfo.ZoneInfo(tzname))
                activated = True
            except Exception:
                pass

        try:
            return self.get_response(request)
        finally:
            if activated:
                timezone.deactivate()


class TerminalActivityMiddleware:
    """
    High-visibility real-time terminal logger for development and production.
    Logs incoming HTTP requests, payloads, actions, streaming progress, and response timings.
    """
    SKIP_PREFIXES = ('/static/', '/favicon.ico')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if any(path.startswith(prefix) for prefix in self.SKIP_PREFIXES):
            return self.get_response(request)

        method = request.method
        user_str = str(request.user) if hasattr(request, 'user') and request.user.is_authenticated else 'Anonymous'
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')

        # Log incoming request
        logger.info("[HTTP HIT] [%s] %s | User: %s | IP: %s", method, path, user_str, ip)

        # Log payload details if POST/PUT
        if method in ('POST', 'PUT', 'PATCH'):
            self._log_payload(request)

        start_time = time.time()
        try:
            response = self.get_response(request)
            elapsed_ms = (time.time() - start_time) * 1000
            status_code = getattr(response, 'status_code', 200)

            logger.info(
                "[HTTP %s] [%s] %s -> %d %s (elapsed: %.1fms)",
                "COMPLETED" if status_code < 400 else "FAILED",
                method,
                path,
                status_code,
                getattr(response, 'reason_phrase', ''),
                elapsed_ms
            )
            return response
        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.exception("[HTTP ERROR] [%s] %s crashed after %.1fms: %s", method, path, elapsed_ms, str(exc))
            raise

    def _log_payload(self, request):
        try:
            # Check for uploaded files
            if hasattr(request, 'FILES') and request.FILES:
                file_summaries = []
                for field_name, f in request.FILES.items():
                    size_kb = max(0.1, round(f.size / 1024, 1))
                    file_summaries.append(f"{f.name} ({size_kb} KB, {getattr(f, 'content_type', '')})")
                logger.info("[FILES ATTACHED] %s", " | ".join(file_summaries))

            # Safely check JSON payload without triggering RawPostDataException
            content_type = request.META.get('CONTENT_TYPE', '')
            if 'application/json' in content_type:
                try:
                    raw_body = request.body
                    if raw_body:
                        data = json.loads(raw_body.decode('utf-8', errors='ignore'))
                        if isinstance(data, dict):
                            msg = data.get('message', '')
                            action = data.get('action')
                            provider = data.get('provider')
                            msg_preview = (msg[:100] + '...') if len(msg) > 100 else msg
                            details = []
                            if provider:
                                details.append(f"provider={provider}")
                            if action:
                                details.append(f"action={action}")
                            if msg:
                                details.append(f"message=\"{msg_preview}\"")
                            if details:
                                logger.info("[PAYLOAD] %s", " | ".join(details))
                except Exception:
                    pass
        except Exception:
            pass


class SelfHealingMiddleware:
    """
    Self-Healing Middleware:
    - Tracks active in-flight request counts across threads to prevent disruptive reloads.
    - If the self-healing engine is actively hot-patching, intercepts incoming user requests
      and returns the professional maintenance page (or 503 JSON) with real-time status.
    - Catches unhandled 500 responses and view exceptions, triggers autonomous self-healing,
      and gracefully displays the self-healing remediation screen to the user.
    """
    SKIP_PREFIXES = ('/static/', '/favicon.ico', '/api/self-healing/')
    _active_requests = 0
    _active_lock = threading.Lock()

    def __init__(self, get_response):
        self.get_response = get_response

    @classmethod
    def get_active_requests_count(cls) -> int:
        with cls._active_lock:
            return cls._active_requests

    @classmethod
    def _increment(cls):
        with cls._active_lock:
            cls._active_requests += 1

    @classmethod
    def _decrement(cls):
        with cls._active_lock:
            cls._active_requests = max(0, cls._active_requests - 1)

    def __call__(self, request):
        path = getattr(request, 'path', '/')
        if any(path.startswith(prefix) for prefix in self.SKIP_PREFIXES):
            return self.get_response(request)

        from core.self_healing import SelfHealingEngine, render_self_healing_response

        # Allow verification subprocesses to run test assertions without 503 interruption
        if os.environ.get('DEVDIALOGUE_HEALING_VERIFICATION') == '1':
            return self.get_response(request)

        # Check if the system is currently actively self-healing
        if SelfHealingEngine.is_healing_active():
            return render_self_healing_response(request, status_code=503)

        self._increment()
        try:
            response = self.get_response(request)
            if getattr(response, 'status_code', 200) in (500, 502, 504):
                # Intercept unhandled 500 server crashes from view
                exc = Exception(f"HTTP {response.status_code} encountered on {path}")
                incident_data = SelfHealingEngine.trigger_healing(
                    exc,
                    request=request,
                    run_async=True
                )
                return render_self_healing_response(request, incident_data=incident_data, status_code=500)
            return response
        except Exception as exc:
            from django.http import Http404
            from django.core.exceptions import PermissionDenied
            if isinstance(exc, (Http404, PermissionDenied)):
                raise
            incident_data = SelfHealingEngine.trigger_healing(exc, request=request, run_async=True)
            return render_self_healing_response(request, incident_data=incident_data, status_code=503)
        finally:
            self._decrement()

    def process_exception(self, request, exception):
        from django.http import Http404
        from django.core.exceptions import PermissionDenied
        if isinstance(exception, (Http404, PermissionDenied)):
            return None

        from core.self_healing import SelfHealingEngine, render_self_healing_response
        incident_data = SelfHealingEngine.trigger_healing(exception, request=request, run_async=True)
        return render_self_healing_response(request, incident_data=incident_data, status_code=503)



