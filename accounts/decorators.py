from django.shortcuts import redirect

def verification_required(view_func):
    """
    Decorator for views that checks if the user is authenticated and verified.
    Redirections:
    - If not logged in: standard login redirect
    - If logged in but not verified: redirect to OTP verification page
    """
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not hasattr(request, '_cached_profile'):
            try:
                request._cached_profile = request.user.profile
            except Exception:
                request._cached_profile = None
        profile = request._cached_profile
        if not profile or not profile.is_verified:
            return redirect('verify_otp')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
