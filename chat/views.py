import json
import re
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone

from accounts.decorators import verification_required
from chat.models import Session, Message, GeneratedCode
from dialogue.interviewer import InterviewerService
from dialogue.synthesizer import SRSSynthesizer
from dialogue.completeness import CompletenessEngine
from generator.file_planner import FilePlanner
from generator.code_builder import CodeBuilder
from llm_engine.router import LLMRouter

def generate_title_from_user_msg(user_msg):
    cleaned = user_msg.strip()
    cleaned_lower = cleaned.lower()
    for prefix in ["i want to build a ", "i want to build ", "build a ", "build ", "create a ", "create ", "make a ", "make "]:
        if cleaned_lower.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            cleaned_lower = cleaned.lower()
            break
            
    words = [w for w in cleaned.split() if w.strip()]
    if words:
        title_words = words[:5]
        title = " ".join(title_words)
        title = re.sub(r'[^\w\s-]', '', title)
        if len(title) > 40:
            title = title[:37] + "..."
        return title.strip().title()
    return "New Chat"

def home_view(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'profile') and request.user.profile.is_verified:
            return redirect('dashboard')
        return redirect('verify_otp')
    return render(request, 'home.html')

def features_view(request):
    return render(request, 'features.html')

def pricing_view(request):
    return render(request, 'pricing.html')

def about_view(request):
    return render(request, 'about.html')

@verification_required
def dashboard_view(request):
    sessions = request.user.sessions.all().order_by('-started_at')
    profile = request.user.profile
    return render(request, 'dashboard.html', {'sessions': sessions, 'profile': profile})

@verification_required
def new_chat_view(request):
    active_sessions = Session.objects.filter(user=request.user, status='active')
    unused_session = None
    for s in active_sessions:
        if s.messages.count() == 0:
            unused_session = s
            break
            
    if unused_session:
        return redirect('chat', session_id=unused_session.id)

    session = Session.objects.create(user=request.user, mode='mode1', status='active')
    return redirect('chat', session_id=session.id)

@verification_required
def create_session_view(request):
    if request.method == 'POST':
        mode = request.POST.get('mode', 'mode1')
        description = request.POST.get('description', '').strip()
        
        if not description:
            return redirect('dashboard')
            
        session = Session.objects.create(
            user=request.user, 
            mode=mode, 
            status='active',
            title=generate_title_from_user_msg(description),
            has_custom_title=True
        )
        
        Message.objects.create(session=session, role='user', content=description)
        history = list(session.messages.values('role', 'content'))
        first_q = InterviewerService.generate_next_question(history)
        Message.objects.create(session=session, role='assistant', content=first_q)
        return redirect('chat', session_id=session.id)
    return redirect('dashboard')

@verification_required
def chat_view(request, session_id):
    session = get_object_or_404(Session, id=session_id, user=request.user)
    messages_list = session.messages.all()
    codes = session.generated_codes.all()
    
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    seven_days_ago = today_start - timedelta(days=7)
    
    all_sessions = Session.objects.filter(user=request.user).order_by('-started_at')
    
    today_sessions = [s for s in all_sessions if s.started_at >= today_start]
    yesterday_sessions = [s for s in all_sessions if today_start > s.started_at >= yesterday_start]
    last_7_days_sessions = [s for s in all_sessions if yesterday_start > s.started_at >= seven_days_ago]
    older_sessions = [s for s in all_sessions if s.started_at < seven_days_ago]
    
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

@verification_required
def send_message_api(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)
        
    session = get_object_or_404(Session, id=session_id, user=request.user)
    
    if session.mode == 'mode1' and session.status == 'completed':
        return JsonResponse({'message': 'Session is completed.', 'status': 'completed'}, status=400)
        
    try:
        data = json.loads(request.body)
        user_content = data.get('message', '').strip()
        provider_name = data.get('provider', None)
    except Exception:
        user_content = request.POST.get('message', '').strip()
        provider_name = None
        
    if not user_content:
        return JsonResponse({'error': 'Message content cannot be empty'}, status=400)
        
    Message.objects.create(session=session, role='user', content=user_content)
    history = list(session.messages.values('role', 'content'))
    
    user_msgs = [m for m in history if m['role'] == 'user']
    assist_msgs = [m for m in history if m['role'] == 'assistant']
    
    response_text = ""
    has_summary = any("### Project Requirements Summary" in m['content'] for m in assist_msgs)
    
    if has_summary:
        confirmation_msg = user_content.lower().strip()
        if session.mode == 'mode1':
            if any(word in confirmation_msg for word in ['yes', 'y', 'proceed', 'generate', 'approve', 'build', 'ok']):
                session.status = 'completed'
                session.save()
                
                summary = SRSSynthesizer.synthesize_summary(history, provider_name=provider_name)
                modules = FilePlanner.get_module_list(summary)
                
                for mod in modules:
                    if not session.generated_codes.filter(module_name=mod).exists():
                        code = CodeBuilder.generate_code_for_module(mod, summary, provider_name=provider_name)
                        GeneratedCode.objects.create(session=session, module_name=mod, code_content=code)
                        
                response_text = (
                    "### 🎉 Codebase Generated Successfully!\n\n"
                    "I have generated the codebase based on your requirements. You can inspect the code in the right panel and download the project ZIP."
                )
            else:
                response_text = InterviewerService.generate_next_question(history, provider_name=provider_name)
        else:
            summary = SRSSynthesizer.synthesize_summary(history, provider_name=provider_name)
            modules = FilePlanner.get_module_list(summary)
            existing_codes = list(session.generated_codes.all())
            
            if len(existing_codes) < len(modules):
                current_mod = modules[len(existing_codes)]
                code = CodeBuilder.generate_code_for_module(current_mod, summary, provider_name=provider_name)
                GeneratedCode.objects.create(session=session, module_name=current_mod, code_content=code)
                
                response_text = (
                    f"### Module {len(existing_codes)+1}/{len(modules)}: `{current_mod}` Generated!\n\n"
                    f"You can view `{current_mod}` in the right panel. Say **yes** to proceed to the next module."
                )
            else:
                session.status = 'completed'
                session.save()
                response_text = "### 🚀 Incremental Generation Complete!\nAll modules have been approved and generated."
    else:
        if CompletenessEngine.should_synthesize_summary(history, user_content):
            response_text = SRSSynthesizer.synthesize_summary(history, is_mode2=(session.mode == 'mode2'), provider_name=provider_name)
        else:
            response_text = InterviewerService.generate_next_question(history, provider_name=provider_name)
                
    Message.objects.create(session=session, role='assistant', content=response_text)
    
    if not session.has_custom_title:
        session.title = generate_title_from_user_msg(user_content)
        session.has_custom_title = True
        session.save()
        
    codes = list(session.generated_codes.values('id', 'module_name'))
    return JsonResponse({
        'response': response_text,
        'status': session.status,
        'codes': codes,
        'title': session.title
    })

@verification_required
def delete_session_view(request, session_id):
    if request.method == 'POST':
        session = get_object_or_404(Session, id=session_id, user=request.user)
        session.delete()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=400)

@verification_required
def rename_session_api(request, session_id):
    if request.method == 'POST':
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

@verification_required
def get_code_file_api(request, code_id):
    code_obj = get_object_or_404(GeneratedCode, id=code_id, session__user=request.user)
    return JsonResponse({
        'module_name': code_obj.module_name,
        'code_content': code_obj.code_content
    })
