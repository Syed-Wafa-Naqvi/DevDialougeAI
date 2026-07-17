from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from core.models import Profile, Session, Message, GeneratedCode
from core.forms import SignUpForm, OTPVerificationForm, ForgotPasswordForm, ResetPasswordForm, UserUpdateForm
from core.decorators import verification_required
from core.dialogue_engine import DialogueEngine

def generate_title_from_llm(user_msg, assistant_reply):
    import re
    cleaned = user_msg.strip()
    
    # Strip common leading prefixes
    cleaned_lower = cleaned.lower()
    for prefix in ["i want to build a ", "i want to build ", "build a ", "build ", "create a ", "create ", "make a ", "make ", "design a ", "design "]:
        if cleaned_lower.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            cleaned_lower = cleaned.lower()
            break
            
    # Common scenarios based on key phrases
    if "api" in cleaned_lower or "rest" in cleaned_lower:
        return "Building REST API Services"
    elif "debug" in cleaned_lower or "error" in cleaned_lower or "bug" in cleaned_lower or "fix" in cleaned_lower:
        return "Debugging Application Code"
    elif "auth" in cleaned_lower or "login" in cleaned_lower or "signup" in cleaned_lower or "password" in cleaned_lower:
        return "User Authentication Design"
    elif "database" in cleaned_lower or "sql" in cleaned_lower or "models" in cleaned_lower:
        return "Database Schema Architecture"
    elif "game" in cleaned_lower:
        return "Game Development Design"
        
    words = [w for w in cleaned.split() if w.strip()]
    if words:
        title_words = words[:5]
        title = " ".join(title_words)
        # Strip trailing/leading punctuation
        title = re.sub(r'[^\w\s-]', '', title)
        if len(title) > 40:
            title = title[:37] + "..."
        return title.strip().title()
        
    return "New Chat"

# 1. Home / Landing Page
def home_view(request):
    if request.user.is_authenticated:
        return redirect('new_chat')
    return render(request, 'home.html')

def features_view(request):
    return render(request, 'features.html')

def pricing_view(request):
    return render(request, 'pricing.html')

def about_view(request):
    return render(request, 'about.html')

# 2. User Sign Up
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False # Deactivate user until verified
            user.set_password(form.cleaned_data['password'])
            user.save()
            
            # Retrieve or create profile (signal automatically creates one, but let's make sure)
            profile, created = Profile.objects.get_or_create(user=user)
            profile.plan = form.cleaned_data['plan']
            profile.save()
            
            # Generate and Send OTP
            otp = profile.generate_otp()
            
            # Send verification email
            subject = "DevDialogue AI - Verify Your Account"
            message = (
                f"Hello {user.username},\n\n"
                f"Welcome to DevDialogue AI!\n\n"
                f"Your 6-digit email verification code (OTP) is: {otp}\n\n"
                f"This code is valid for 2 minutes. If you did not sign up for this account, please ignore this email.\n\n"
                f"Best regards,\n"
                f"The DevDialogue AI Team"
            )
            try:
                send_mail(
                    subject, 
                    message, 
                    settings.DEFAULT_FROM_EMAIL, 
                    [user.email], 
                    fail_silently=False
                )
                # Store user ID in session to allow OTP verification
                request.session['pre_verified_user_id'] = user.id
                messages.success(request, "Registration successful! We have sent a 6-digit verification code to your email.")
                return redirect('verify_otp')
            except Exception as e:
                messages.error(request, f"Error sending verification email: {str(e)}. Please check SMTP configuration.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        # Pre-select plan if passed in query param
        selected_plan = request.GET.get('plan', 'basic')
        if selected_plan not in ['basic', 'pro', 'premium']:
            selected_plan = 'basic'
        form = SignUpForm(initial={'plan': selected_plan})
        
    return render(request, 'signup.html', {'form': form})

# 3. OTP Verification
def verify_otp_view(request):
    user_id = request.session.get('pre_verified_user_id')
    if not user_id:
        messages.error(request, "Session expired or invalid access. Please sign up or log in first.")
        return redirect('signup')
        
    user = get_object_or_404(User, id=user_id)
    profile = user.profile
    
    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            otp_entered = form.cleaned_data['otp']
            if profile.is_otp_valid(otp_entered):
                # Verify and Activate User
                profile.is_verified = True
                profile.otp = None
                profile.otp_created_at = None
                profile.save()
                
                user.is_active = True
                user.save()
                
                # Automatically login the user
                login(request, user)
                
                # Clear session state
                del request.session['pre_verified_user_id']
                
                messages.success(request, f"Welcome {user.username}! Your account has been verified successfully.")
                return redirect('dashboard')
            else:
                form.add_error('otp', "Invalid or expired OTP. Please try again.")
    else:
        form = OTPVerificationForm()
        
    return render(request, 'verify_otp.html', {'form': form, 'email': user.email})

# 3b. Resend OTP
def resend_otp_view(request):
    user_id = request.session.get('pre_verified_user_id')
    is_reset = False
    if not user_id:
        user_id = request.session.get('reset_password_user_id')
        is_reset = True
        if not user_id:
            return JsonResponse({'error': 'Session expired. Please start over.'}, status=400)
        
    user = get_object_or_404(User, id=user_id)
    profile = user.profile
    
    # Generate and Send OTP
    otp = profile.generate_otp()
    
    if is_reset:
        subject = "DevDialogue AI - Reset Your Password"
        message = (
            f"Hello {user.username},\n\n"
            f"We received a request to reset your password for your DevDialogue AI account.\n\n"
            f"Your new 6-digit verification code (OTP) is: {otp}\n\n"
            f"This code is valid for 2 minutes. If you did not request a password reset, please ignore this email.\n\n"
            f"Best regards,\n"
            f"The DevDialogue AI Team"
        )
    else:
        subject = "DevDialogue AI - Verify Your Account"
        message = (
            f"Hello {user.username},\n\n"
            f"Welcome to DevDialogue AI!\n\n"
            f"Your new 6-digit email verification code (OTP) is: {otp}\n\n"
            f"This code is valid for 2 minutes. If you did not sign up for this account, please ignore this email.\n\n"
            f"Best regards,\n"
            f"The DevDialogue AI Team"
        )
        
    try:
        send_mail(
            subject, 
            message, 
            settings.DEFAULT_FROM_EMAIL, 
            [user.email], 
            fail_silently=False
        )
        return JsonResponse({'success': True, 'message': 'A new OTP has been sent to your email.'})
    except Exception as e:
        return JsonResponse({'error': f'Error sending email: {str(e)}'}, status=500)

# 4. User Login
def login_view(request):
    if request.user.is_authenticated:
        latest_session = request.user.sessions.all().order_by('-started_at').first()
        if latest_session:
            return redirect('chat', session_id=latest_session.id)
        return redirect('dashboard')
        
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                # Check verification status
                if hasattr(user, 'profile') and not user.profile.is_verified:
                    # Deactivate user temporarily if they bypassed somehow and send new OTP
                    user.is_active = False
                    user.save()
                    profile = user.profile
                    otp = profile.generate_otp()
                    
                    send_mail(
                        "DevDialogue AI - Verify Your Account",
                        f"Your verification code is: {otp}",
                        settings.DEFAULT_FROM_EMAIL,
                        [user.email],
                        fail_silently=True
                    )
                    request.session['pre_verified_user_id'] = user.id
                    messages.warning(request, "Your email is not verified. A new OTP has been sent to your email.")
                    return redirect('verify_otp')
                
                login(request, user)
                messages.success(request, f"Welcome back, {username}!")
                return redirect('dashboard')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = AuthenticationForm()
    return render(request, 'login.html', {'form': form})

# 5. User Logout
def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('home')

# 6. Dashboard
@verification_required
def dashboard_view(request):
    # Redirect to latest session unless explicitly going back using ?back=true
    if 'back' not in request.GET:
        latest_session = request.user.sessions.all().order_by('-started_at').first()
        if latest_session:
            return redirect('chat', session_id=latest_session.id)
            
    sessions = request.user.sessions.all().order_by('-started_at')
    profile = request.user.profile
    return render(request, 'dashboard.html', {'sessions': sessions, 'profile': profile})

# 7. Create New Session (Quick/Auto Mode 1)
@verification_required
def new_chat_view(request):
    # Check if there is already an active unused session (no real messages sent yet)
    active_sessions = Session.objects.filter(user=request.user, status='active')
    unused_session = None
    for s in active_sessions:
        if s.messages.count() == 0:
            unused_session = s
            break
            
    if unused_session:
        return redirect('chat', session_id=unused_session.id)

    # Create a fresh empty session — no pre-inserted messages.
    # The dialogue engine will respond when the user sends their first real message.
    session = Session.objects.create(user=request.user, mode='mode1', status='active')
    return redirect('chat', session_id=session.id)

# 8. Delete Chat Session permanently
@verification_required
def delete_session_view(request, session_id):
    if request.method == 'POST':
        session = get_object_or_404(Session, id=session_id, user=request.user)
        session.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

# 9. Create New Session
@verification_required
def create_session_view(request):
    if request.method == 'POST':
        mode = request.POST.get('mode', 'mode1')
        description = request.POST.get('description', '').strip()
        
        if not description:
            messages.error(request, "Please enter an initial project description.")
            return redirect('dashboard')
            
        # Ask first question
        first_q = DialogueEngine.QUESTIONS[0][1]
        
        # Create a new session
        session = Session.objects.create(
            user=request.user, 
            mode=mode, 
            status='active',
            title=generate_title_from_llm(description, first_q),
            has_custom_title=True
        )
        
        # Save the initial user project description as message 1
        Message.objects.create(session=session, role='user', content=description)
        
        # Save first question as message 2
        Message.objects.create(session=session, role='assistant', content=first_q)
        
        return redirect('chat', session_id=session.id)
    return redirect('dashboard')

# 8. Interactive Chat View
@verification_required
def chat_view(request, session_id):
    from datetime import timedelta
    session = get_object_or_404(Session, id=session_id, user=request.user)
    messages_list = session.messages.all()
    codes = session.generated_codes.all()
    
    # Fetch historical sessions
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    seven_days_ago = today_start - timedelta(days=7)
    
    all_sessions = Session.objects.filter(user=request.user).order_by('-started_at')
    
    today_sessions = []
    yesterday_sessions = []
    last_7_days_sessions = []
    older_sessions = []
    
    for s in all_sessions:
        if s.started_at >= today_start:
            today_sessions.append(s)
        elif s.started_at >= yesterday_start:
            yesterday_sessions.append(s)
        elif s.started_at >= seven_days_ago:
            last_7_days_sessions.append(s)
        else:
            older_sessions.append(s)
    # Empty session (no messages at all) = first-load / greeting state
    is_first_load = messages_list.count() == 0
            
    return render(request, 'chat.html', {
        'session': session,
        'chat_messages': messages_list,
        'generated_codes': codes,
        'today_sessions': today_sessions,
        'yesterday_sessions': yesterday_sessions,
        'last_7_days_sessions': last_7_days_sessions,
        'older_sessions': older_sessions,
        'is_first_load': is_first_load,
    })

# 9. Send Message API (AJAX/Fetch)
@verification_required
def send_message_api(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)
        
    session = get_object_or_404(Session, id=session_id, user=request.user)
    
    # Check if session is already completed and user is in Mode 1
    if session.mode == 'mode1' and session.status == 'completed':
        return JsonResponse({
            'message': 'This session is completed. No more messages can be sent.',
            'status': 'completed'
        }, status=400)
        
    import json
    try:
        data = json.loads(request.body)
        user_content = data.get('message', '').strip()
    except Exception:
        user_content = request.POST.get('message', '').strip()
        
    if not user_content:
        return JsonResponse({'error': 'Message content cannot be empty'}, status=400)
        
    # Get response from Dialogue Engine
    response_text = DialogueEngine.process_message(session, user_content)
    
    # Auto-generate title after the first real interaction
    if not session.has_custom_title:
        real_user_msg = session.messages.filter(role='user').first()
        if real_user_msg:
            real_assistant_reply = session.messages.filter(role='assistant', id__gt=real_user_msg.id).first()
            if real_assistant_reply:
                try:
                    session.title = generate_title_from_llm(real_user_msg.content, real_assistant_reply.content)
                    session.has_custom_title = True
                    session.save()
                except Exception:
                    pass
    
    # Fetch all generated codes up to now
    codes = list(session.generated_codes.values('id', 'module_name'))
    
    return JsonResponse({
        'response': response_text,
        'status': session.status,
        'codes': codes,
        'title': session.title if session.has_custom_title else None
    })

@verification_required
def rename_session_api(request, session_id):
    if request.method == 'POST':
        import json
        try:
            data = json.loads(request.body)
            new_title = data.get('title', '').strip()
        except Exception:
            new_title = request.POST.get('title', '').strip()
            
        if not new_title:
            return JsonResponse({'error': 'Title cannot be empty'}, status=400)
            
        session = get_object_or_404(Session, id=session_id, user=request.user)
        session.title = new_title[:255]
        session.has_custom_title = True
        session.save()
        return JsonResponse({'status': 'success', 'title': session.title})
        
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=400)

# 10. Get Code Content API
@verification_required
def get_code_file_api(request, code_id):
    code_obj = get_object_or_404(GeneratedCode, id=code_id, session__user=request.user)
    return JsonResponse({
        'module_name': code_obj.module_name,
        'code_content': code_obj.code_content
    })

# 11. Forgot Password Flow
def forgot_password_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.get(email=email)
            profile = user.profile
            
            # Generate OTP
            otp = profile.generate_otp()
            
            # Send Email
            subject = "DevDialogue AI - Reset Your Password"
            message = (
                f"Hello {user.username},\n\n"
                f"We received a request to reset your password for your DevDialogue AI account.\n\n"
                f"Your 6-digit verification code (OTP) is: {otp}\n\n"
                f"This code is valid for 2 minutes. If you did not request a password reset, please ignore this email.\n\n"
                f"Best regards,\n"
                f"The DevDialogue AI Team"
            )
            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=False
                )
                request.session['reset_password_user_id'] = user.id
                messages.success(request, "A password reset code has been sent to your email.")
                return redirect('reset_password')
            except Exception as e:
                messages.error(request, f"Error sending email: {str(e)}")
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
                # Valid OTP! Reset password
                user.set_password(new_password)
                user.save()
                
                # Clear OTP
                profile.otp = None
                profile.otp_created_at = None
                profile.save()

                # Clean session
                del request.session['reset_password_user_id']

                messages.success(request, "Your password has been reset successfully. You can now log in.")
                return redirect('login')
            else:
                form.add_error('otp', "Invalid or expired OTP.")
    else:
        form = ResetPasswordForm()

    return render(request, 'reset_password.html', {'form': form, 'email': user.email})


# 12. Account Settings Dashboard
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
                
                # Handle profile picture
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
    
    # Instantiate blank forms if it was GET or had validation errors
    user_form = UserUpdateForm(instance=user)
    password_form = PasswordChangeForm(user=user)
    
    return render(request, 'settings.html', {
        'profile': profile,
        'user_form': user_form,
        'password_form': password_form,
    })
