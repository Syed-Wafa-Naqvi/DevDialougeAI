import zoneinfo
from django.utils import timezone

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

