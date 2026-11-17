import json
import logging
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


