from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from core.models import Profile, Session, Message, GeneratedCode
from core.forms import SignUpForm, OTPVerificationForm
from core.decorators import verification_required
from core.dialogue_engine import DialogueEngine

# 1. Home / Landing Page
def home_view(request):
    if request.user.is_authenticated:
        latest_session = request.user.sessions.all().order_by('-started_at').first()
        if latest_session:
            return redirect('chat', session_id=latest_session.id)
        return redirect('dashboard')
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
    if not user_id:
        return JsonResponse({'error': 'Session expired. Please sign up again.'}, status=400)
        
    user = get_object_or_404(User, id=user_id)
    profile = user.profile
    
    # Generate and Send OTP
    otp = profile.generate_otp()
    
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

# 7. Create New Session
@verification_required
def create_session_view(request):
    if request.method == 'POST':
        mode = request.POST.get('mode', 'mode1')
        description = request.POST.get('description', '').strip()
        
        if not description:
            messages.error(request, "Please enter an initial project description.")
            return redirect('dashboard')
            
        # Create a new session
        session = Session.objects.create(user=request.user, mode=mode, status='active')
        
        # Save the initial user project description as message 1
        Message.objects.create(session=session, role='user', content=description)
        
        # Ask first question
        first_q = DialogueEngine.QUESTIONS[0][1]
        Message.objects.create(session=session, role='assistant', content=first_q)
        
        return redirect('chat', session_id=session.id)
    return redirect('dashboard')

# 8. Interactive Chat View
@verification_required
def chat_view(request, session_id):
    session = get_object_or_404(Session, id=session_id, user=request.user)
    messages_list = session.messages.all()
    codes = session.generated_codes.all()
    return render(request, 'chat.html', {
        'session': session,
        'chat_messages': messages_list,
        'generated_codes': codes
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
    
    # Fetch all generated codes up to now
    codes = list(session.generated_codes.values('id', 'module_name'))
    
    return JsonResponse({
        'response': response_text,
        'status': session.status,
        'codes': codes
    })

# 10. Get Code Content API
@verification_required
def get_code_file_api(request, code_id):
    code_obj = get_object_or_404(GeneratedCode, id=code_id, session__user=request.user)
    return JsonResponse({
        'module_name': code_obj.module_name,
        'code_content': code_obj.code_content
    })
