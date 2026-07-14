from django.shortcuts import redirect
from django.contrib.auth.decorators import user_passes_test

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
        if not hasattr(request.user, 'profile') or not request.user.profile.is_verified:
            return redirect('verify_otp')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
