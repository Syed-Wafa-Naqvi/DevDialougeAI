from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib import messages
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction, models

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
                    unverified_users = User.objects.filter(
                        models.Q(username=username) | models.Q(email=email),
                        is_active=False
                    )
                    for unverified_user in unverified_users:
                        if hasattr(unverified_user, 'profile') and not unverified_user.profile.is_verified:
                            unverified_user.delete()

                    user = form.save(commit=False)
                    user.is_active = False
                    user.set_password(password)
                    user.save()
                    
                    profile, created = Profile.objects.get_or_create(user=user)
                    profile.plan = plan
                    profile.save()
                    
                    otp = profile.generate_otp()

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
            except Exception as e:
                messages.error(request, f"Error processing signup: {str(e)}. Please try again.")
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
            if profile.is_otp_valid(otp_entered):
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
                form.add_error('otp', "Invalid or expired OTP. Please try again.")
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
    
    otp = profile.generate_otp()
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
        return JsonResponse({'error': f'Error sending email: {str(e)}'}, status=500)


def login_view(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'profile') and request.user.profile.is_verified:
            return redirect('dashboard')
        return redirect('verify_otp')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                if hasattr(user, 'profile') and not user.profile.is_verified:
                    user.is_active = False
                    user.save()
                    profile = user.profile
                    otp = profile.generate_otp()
                    request.session['pre_verified_user_id'] = user.id
                    messages.warning(request, "Your email is not verified. A new OTP has been sent.")
                    return redirect('verify_otp')
                
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
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.get(email=email)
            profile = user.profile
            
            otp = profile.generate_otp()
            print(f"\n==========================================")
            print(f"[DevDialogue AI] Reset Password OTP for {user.username} ({user.email}): {otp}")
            print(f"==========================================\n")
            
            request.session['reset_password_user_id'] = user.id
            subject = "DevDialogue AI - Reset Your Password"
            message = f"Hello {user.username},\n\nYour OTP to reset password is: {otp}\n\nBest regards,\nThe DevDialogue AI Team"
            
            try:
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
                messages.success(request, "A password reset code has been sent to your email.")
            except Exception as e:
                if settings.DEBUG:
                    messages.warning(request, f"Reset code generated! For development, your OTP code is: {otp}")
                else:
                    messages.warning(request, "Reset code generated, but email delivery failed.")
            
            return redirect('reset_password')
        else:
            messages.error(request, "Please correct the error below.")
    else:
        form = ForgotPasswordForm()

    return render(request, 'forgot_password.html', {'form': form})


def reset_password_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    user_id = request.session.get('reset_password_user_id')
    if not user_id:
        messages.error(request, "Session invalid or expired. Please request password reset again.")
        return redirect('forgot_password')

    user = get_object_or_404(User, id=user_id)
    profile = user.profile

    if request.method == 'POST':
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            new_password = form.cleaned_data['new_password']

            if profile.is_otp_valid(otp):
                user.set_password(new_password)
                user.save()
                
                profile.otp = None
                profile.otp_created_at = None
                profile.save()

                del request.session['reset_password_user_id']

                messages.success(request, "Your password has been reset successfully. You can now log in.")
                return redirect('login')
            else:
                form.add_error('otp', "Invalid or expired OTP.")
    else:
        form = ResetPasswordForm()

    return render(request, 'reset_password.html', {'form': form, 'email': user.email})


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
    
    user_form = UserUpdateForm(instance=user)
    password_form = PasswordChangeForm(user=user)
    
    return render(request, 'settings.html', {
        'profile': profile,
        'user_form': user_form,
        'password_form': password_form,
    })
