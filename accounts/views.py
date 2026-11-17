from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib import messages
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction, models
from django.utils import timezone
from django.core.cache import cache

def get_client_ip(request):
    remote_addr = request.META.get('REMOTE_ADDR', '127.0.0.1')
    if getattr(settings, 'USE_X_FORWARDED_HOST', False) or getattr(settings, 'TRUST_PROXY_HEADERS', False):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
    return remote_addr

def is_rate_limited(key: str, max_attempts: int, timeout_seconds: int) -> bool:
    attempts = cache.get(key, 0)
    if attempts >= max_attempts:
        return True
    cache.set(key, attempts + 1, timeout=timeout_seconds)
    return False

def reset_rate_limit(key: str):
    cache.delete(key)

from accounts.models import Profile
from accounts.forms import SignUpForm, OTPVerificationForm, ForgotPasswordForm, ResetPasswordForm, UserUpdateForm
from accounts.decorators import verification_required

def signup_view(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'profile') and request.user.profile.is_verified:
            return redirect('dashboard')
        return redirect('verify_otp')
        
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            plan = form.cleaned_data['plan']

            try:
                with transaction.atomic():
                    if User.objects.filter(models.Q(username=username) | models.Q(email=email)).exists():
                        messages.error(request, "An account with this username or email already exists. Please log in or use a different email.")
                        return render(request, 'signup.html', {'form': form})

                    user = form.save(commit=False)
                    user.is_active = False
                    user.set_password(password)
                    user.save()
                    
                    profile, created = Profile.objects.get_or_create(user=user)
                    profile.plan = plan
                    profile.save()
                    
                    otp = profile.generate_otp()

                if settings.DEBUG:
                    print(f"\n==========================================")
                    print(f"[DevDialogue AI] Verification OTP for {user.username} ({user.email}): {otp}")
                    print(f"==========================================\n")
                
                request.session['pre_verified_user_id'] = user.id
                
                subject = "DevDialogue AI - Verify Your Account"
                message = (
                    f"Hello {user.username},\n\n"
                    f"Welcome to DevDialogue AI!\n\n"
                    f"Your 6-digit email verification code (OTP) is: {otp}\n\n"
                    f"This code is valid for 2 minutes.\n\n"
                    f"Best regards,\nThe DevDialogue AI Team"
                )
                try:
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
                    messages.success(request, "Registration successful! We have sent a 6-digit verification code to your email.")
                except Exception as e:
                    if settings.DEBUG:
                        messages.warning(request, f"Account created! For development testing, your OTP is: {otp}")
                    else:
                        messages.warning(request, "Account created! Verification email delivery failed. Click Resend OTP.")
                
                return redirect('verify_otp')
            except Exception:
                messages.error(request, "Error processing signup. Please check your information and try again.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        selected_plan = request.GET.get('plan', 'basic')
        if selected_plan not in ['basic', 'pro', 'premium']:
            selected_plan = 'basic'
        form = SignUpForm(initial={'plan': selected_plan})
        
    return render(request, 'signup.html', {'form': form})


def verify_otp_view(request):
    user = None
    if request.user.is_authenticated:
        user = request.user
    else:
        user_id = request.session.get('pre_verified_user_id')
        if user_id:
            user = User.objects.filter(id=user_id).first()

    if not user:
        messages.error(request, "Session expired or invalid access. Please log in or sign up first.")
        return redirect('login')
        
    profile = getattr(user, 'profile', None)
    if not profile:
        profile = Profile.objects.create(user=user)
        
    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            otp_entered = form.cleaned_data['otp']
            is_valid, reason = profile.verify_otp_with_reason(otp_entered)
            if is_valid:
                profile.is_verified = True
                profile.otp = None
                profile.otp_created_at = None
                profile.save()
                
                user.is_active = True
                user.save()
                
                login(request, user)
                if 'pre_verified_user_id' in request.session:
                    del request.session['pre_verified_user_id']
                
                messages.success(request, f"Welcome {user.username}! Your account has been verified successfully.")
                return redirect('dashboard')
            else:
                form.add_error('otp', reason)
    else:
        form = OTPVerificationForm()
        
    return render(request, 'verify_otp.html', {'form': form, 'email': user.email})


def resend_otp_view(request):
    user = None
    is_reset = False
    if request.user.is_authenticated:
        user = request.user
    else:
        user_id = request.session.get('pre_verified_user_id')
        if not user_id:
            user_id = request.session.get('reset_password_user_id')
            is_reset = True
        if user_id:
            user = User.objects.filter(id=user_id).first()

    if not user:
        return JsonResponse({'error': 'Session expired. Please start over.'}, status=400)
        
    profile = getattr(user, 'profile', None)
    if not profile:
        profile = Profile.objects.create(user=user)

    can_resend, reason = profile.can_resend_otp()
    if not can_resend:
        return JsonResponse({'error': reason}, status=429)
    
    otp = profile.generate_otp()
    if settings.DEBUG:
        print(f"\n==========================================")
        print(f"[DevDialogue AI] Resent OTP for {user.username} ({user.email}): {otp}")
        print(f"==========================================\n")
    
    subject = "DevDialogue AI - Reset Your Password" if is_reset else "DevDialogue AI - Verify Your Account"
    message = f"Hello {user.username},\n\nYour new verification code (OTP) is: {otp}\n\nBest regards,\nThe DevDialogue AI Team"
        
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        return JsonResponse({'success': True, 'message': 'A new OTP has been sent to your email.'})
    except Exception as e:
        if settings.DEBUG:
            return JsonResponse({'success': True, 'message': f'For local testing, your new OTP is: {otp}'})
        return JsonResponse({'error': 'Error sending email. Please try again later.'}, status=500)



def login_view(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'profile') and request.user.profile.is_verified:
            return redirect('dashboard')
        return redirect('verify_otp')
        
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        ip = get_client_ip(request)
        rl_key = f"login_{ip}_{username}"

        if is_rate_limited(rl_key, max_attempts=10, timeout_seconds=300):
            messages.error(request, "Too many login attempts. Please wait 5 minutes before trying again.")
            return render(request, 'login.html', {'form': AuthenticationForm()})

        form = AuthenticationForm(request, data=request.POST)

        # Check if user exists and is unverified (Django's default authenticate returns None for inactive users)
        existing_user = User.objects.filter(username=username).first()
        if existing_user and existing_user.check_password(password):
            profile = getattr(existing_user, 'profile', None)
            if profile and not profile.is_verified:
                reset_rate_limit(rl_key)
                otp = profile.generate_otp()
                if settings.DEBUG:
                    print(f"\n==========================================")
                    print(f"[DevDialogue AI] Verification OTP for unverified login {existing_user.username} ({existing_user.email}): {otp}")
                    print(f"==========================================\n")
                request.session['pre_verified_user_id'] = existing_user.id

                subject = "DevDialogue AI - Verify Your Account"
                message = (
                    f"Hello {existing_user.username},\n\n"
                    f"Your email is not verified yet. Your 6-digit verification code (OTP) is: {otp}\n\n"
                    f"This code is valid for 2 minutes.\n\n"
                    f"Best regards,\nThe DevDialogue AI Team"
                )
                try:
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [existing_user.email], fail_silently=False)
                    messages.warning(request, "Your email is not verified. A new verification OTP has been sent to your email.")
                except Exception:
                    if settings.DEBUG:
                        messages.warning(request, f"Your email is not verified. Dev OTP is: {otp}")
                    else:
                        messages.warning(request, "Your email is not verified. Please verify your OTP.")
                return redirect('verify_otp')

        user = authenticate(username=username, password=password)
        if user is not None:
            reset_rate_limit(rl_key)
            login(request, user)
            messages.success(request, f"Welcome back, {username}!")
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('home')


def forgot_password_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        ip = get_client_ip(request)
        if is_rate_limited(f"forgot_pw_{ip}", max_attempts=5, timeout_seconds=300):
            messages.error(request, "Too many password reset requests. Please wait a few minutes.")
            return render(request, 'forgot_password.html', {'form': ForgotPasswordForm()})

        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            request.session['reset_password_email'] = email

            # Use filter().first() to avoid MultipleObjectsReturned crash with duplicate emails
            user = User.objects.filter(email=email).order_by('-date_joined').first()
            if user:
                profile = getattr(user, 'profile', None)
                if not profile:
                    profile = Profile.objects.create(user=user)
                otp = profile.generate_otp()
                if settings.DEBUG:
                    print(f"\n==========================================")
                    print(f"[DevDialogue AI] Reset Password OTP for {user.username} ({user.email}): {otp}")
                    print(f"==========================================\n")
                
                request.session['reset_password_user_id'] = user.id
                subject = "DevDialogue AI - Reset Your Password"
                message = f"Hello {user.username},\n\nYour OTP to reset password is: {otp}\n\nBest regards,\nThe DevDialogue AI Team"
                
                try:
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
                except Exception:
                    pass
            else:
                request.session['reset_password_user_id'] = None

            # Generic success message to eliminate account enumeration
            messages.success(request, "If an account exists with this email address, a password reset code has been sent.")
            return redirect('reset_password')
        else:
            messages.error(request, "Please enter a valid email address.")
    else:
        form = ForgotPasswordForm()

    return render(request, 'forgot_password.html', {'form': form})


def reset_password_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    email = request.session.get('reset_password_email')
    if not email:
        messages.error(request, "Session invalid or expired. Please request password reset again.")
        return redirect('forgot_password')

    user_id = request.session.get('reset_password_user_id')
    user = User.objects.filter(id=user_id).first() if user_id else None
    profile = getattr(user, 'profile', None) if user else None

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            new_password = form.cleaned_data['new_password']

            is_valid, reason = profile.verify_otp_with_reason(otp) if profile else (False, "Invalid or expired OTP.")
            if is_valid:
                user.set_password(new_password)
                user.save()
                
                profile.otp = None
                profile.otp_created_at = None
                profile.save()

                if 'reset_password_user_id' in request.session:
                    del request.session['reset_password_user_id']
                if 'reset_password_email' in request.session:
                    del request.session['reset_password_email']

                messages.success(request, "Your password has been reset successfully. You can now log in.")
                return redirect('login')
            else:
                form.add_error('otp', reason)
    else:
        form = ResetPasswordForm()

    return render(request, 'reset_password.html', {'form': form, 'email': email})


def get_user_usage_stats(user):
    """
    Computes real-time, dynamic token usage and quotas for the user.
    Aggregates LLMCallLogs across all user sessions and interactions for the current month.
    """
    from django.db.models import Sum, Q, Count
    from django.utils import timezone
    from llm_engine.models import LLMCallLog
    from chat.models import Message, Session

    profile = getattr(user, 'profile', None)
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Next month reset date (1st of next month)
    if now.month == 12:
        next_month_reset = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month_reset = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    # 1. Monthly token usage from LLMCallLog
    user_logs = LLMCallLog.objects.filter(Q(user=user) | Q(session__user=user))
    month_logs = user_logs.filter(created_at__gte=month_start)

    month_agg = month_logs.aggregate(
        in_tok=Sum('input_tokens'),
        out_tok=Sum('output_tokens'),
        total_calls=Count('id')
    )
    month_in = month_agg['in_tok'] or 0
    month_out = month_agg['out_tok'] or 0
    monthly_tokens = month_in + month_out
    total_calls_this_month = month_agg['total_calls'] or 0

    # Fallback to chat messages if user has messages but no call logs (e.g. earlier sessions or tests)
    if monthly_tokens == 0:
        month_messages = Message.objects.filter(session__user=user, timestamp__gte=month_start)
        if month_messages.exists():
            monthly_tokens = sum(max(1, len(m.content or '') // 4) for m in month_messages)
            total_calls_this_month = month_messages.filter(role='assistant').count()

    # 2. All-time token usage
    all_agg = user_logs.aggregate(
        in_tok=Sum('input_tokens'),
        out_tok=Sum('output_tokens'),
        all_calls=Count('id')
    )
    all_time_tokens = (all_agg['in_tok'] or 0) + (all_agg['out_tok'] or 0)
    if all_time_tokens == 0:
        all_messages = Message.objects.filter(session__user=user)
        if all_messages.exists():
            all_time_tokens = sum(max(1, len(m.content or '') // 4) for m in all_messages)

    # 3. Monthly token quota based on user plan
    plan_limits = getattr(settings, 'PLAN_TOKEN_LIMITS', {
        'basic': 1_000_000,
        'pro': 5_000_000,
        'premium': 20_000_000,
    })
    plan_name = getattr(profile, 'plan', 'basic') or 'basic'
    monthly_quota = plan_limits.get(plan_name, 1_000_000)
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        monthly_quota = 50_000_000

    if monthly_quota > 0:
        usage_pct = min(100.0, (monthly_tokens / monthly_quota) * 100)
    else:
        usage_pct = 0.0

    remaining_tokens = max(0, monthly_quota - monthly_tokens)

    # 4. Breakdown by category/purpose
    purpose_labels = dict(LLMCallLog.PURPOSE_CHOICES)
    purpose_breakdown = []
    if month_logs.exists():
        grouped = month_logs.values('purpose').annotate(
            in_tok=Sum('input_tokens'),
            out_tok=Sum('output_tokens'),
            calls=Count('id')
        ).order_by('-calls')
        for item in grouped:
            p_tot = (item['in_tok'] or 0) + (item['out_tok'] or 0)
            purpose_breakdown.append({
                'purpose': item['purpose'],
                'label': purpose_labels.get(item['purpose'], item['purpose'].title()),
                'tokens': p_tot,
                'tokens_formatted': f"{p_tot:,}",
                'calls': item['calls'],
                'pct': round((p_tot / max(monthly_tokens, 1)) * 100, 1)
            })

    total_sessions_count = Session.objects.filter(user=user).count()

    return {
        'monthly_tokens': monthly_tokens,
        'monthly_tokens_formatted': f"{monthly_tokens:,}",
        'monthly_quota': monthly_quota,
        'monthly_quota_formatted': f"{monthly_quota:,}",
        'usage_percentage': f"{usage_pct:.1f}",
        'usage_percentage_float': usage_pct,
        'remaining_tokens': remaining_tokens,
        'remaining_tokens_formatted': f"{remaining_tokens:,}",
        'all_time_tokens': all_time_tokens,
        'all_time_tokens_formatted': f"{all_time_tokens:,}",
        'total_calls_this_month': total_calls_this_month,
        'total_sessions_count': total_sessions_count,
        'next_reset_date': next_month_reset.strftime('%b %d, %Y'),
        'purpose_breakdown': purpose_breakdown,
        'plan_display': profile.get_plan_display() if profile else 'Basic',
        'has_custom_keys': bool(profile and (profile.encrypted_openai_key or profile.encrypted_gemini_key)),
    }


@verification_required
def settings_view(request):
    user = request.user
    profile = user.profile
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_profile':
            user_form = UserUpdateForm(request.POST, instance=user)
            if user_form.is_valid():
                user_form.save()
                
                if 'profile_picture' in request.FILES:
                    profile.profile_picture = request.FILES['profile_picture']
                    profile.save()
                elif request.POST.get('remove_profile_picture') == 'true':
                    if profile.profile_picture:
                        profile.profile_picture.delete()
                    profile.profile_picture = None
                    profile.save()
                    
                messages.success(request, "Account settings updated successfully.")
                return redirect('settings')
            else:
                messages.error(request, "Failed to update profile. Please check the errors.")
        
        elif action == 'change_password':
            password_form = PasswordChangeForm(user=user, data=request.POST)
            if password_form.is_valid():
                user_form_obj = password_form.save()
                update_session_auth_hash(request, user_form_obj)
                messages.success(request, "Your password has been changed successfully.")
                return redirect('settings')
            else:
                messages.error(request, "Failed to change password. Please check the errors.")

        elif action == 'update_keys':
            gemini_key = request.POST.get('gemini_api_key', '').strip()
            openai_key = request.POST.get('openai_api_key', '').strip()
            if gemini_key and not gemini_key.startswith('•'):
                profile.set_gemini_key(gemini_key)
            elif gemini_key == '':
                profile.encrypted_gemini_key = ''
                
            if openai_key and not openai_key.startswith('•'):
                profile.set_openai_key(openai_key)
            elif openai_key == '':
                profile.encrypted_openai_key = ''
                
            profile.save()
            messages.success(request, "Custom API Keys updated successfully.")
            return redirect('settings')
    
    user_form = UserUpdateForm(instance=user)
    password_form = PasswordChangeForm(user=user)
    usage_data = get_user_usage_stats(user)
    
    return render(request, 'settings.html', {
        'profile': profile,
        'user_form': user_form,
        'password_form': password_form,
        'usage': usage_data,
    })


@verification_required
def user_usage_api(request):
    usage_data = get_user_usage_stats(request.user)
    return JsonResponse(usage_data)
