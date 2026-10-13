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
    vowels = set("aeiouy")
    
    # Filter out gibberish / non-words
    if words:
        first_word = words[0].lower()
        if len(first_word) >= 4 and not any(v in first_word for v in vowels):
            return "New Chat"
        if len(first_word) >= 6 and sum(c in vowels for c in first_word) <= 1:
            return "New Chat"

    if words:
        title_words = words[:5]
        title = " ".join(title_words)
        title = re.sub(r'[^\w\s-]', '', title)
        if len(title) > 40:
            title = title[:37] + "..."
        clean_title = title.strip().title()
        if clean_title.lower() in ["hey", "hello", "hi", "test", "what"]:
            return "New Chat"
        return clean_title
    return "New Chat"

def extract_code_files_from_markdown(content: str) -> list:
    """Extracts file paths and source code blocks formatted in markdown."""
    files = []
    seen = set()
    exts = r'(?:dart|py|js|jsx|ts|tsx|html|css|json|yaml|yml|go|rs|sh|bat|sql|toml|env|md)'

    # Pattern 1: Heading/Label containing a file path, followed by a fenced code block
    # Matches: "### 2. Core Game Model & 2D Grid (`lib/features/game/models/point.dart`)"
    # Matches: "### `lib/main.dart`"
    # Matches: "**pubspec.yaml**"
    p1 = re.compile(
        r'(?:^|\n)(?:#{1,6}|\*\*|[0-9]+\.)[^\n]*?`?([a-zA-Z0-9_\-\./\\]+\.' + exts + r')`?[^\n]*\n+```(?:\w+)?\n(.*?)```',
        re.DOTALL
    )
    for match in p1.finditer(content):
        fn = match.group(1).strip().lstrip('/')
        code = match.group(2).strip()
        if fn not in seen and fn.lower() not in ('bash', 'sh', 'text', 'markdown', 'json'):
            seen.add(fn)
            files.append((fn, code))

    # Pattern 2: ```lang:filepath \n code \n ```
    p2 = re.compile(r'```[a-zA-Z0-9_]+:([a-zA-Z0-9_\-\./\\]+\.' + exts + r')\n(.*?)```', re.DOTALL)
    for match in p2.finditer(content):
        fn = match.group(1).strip().lstrip('/')
        code = match.group(2).strip()
        if fn not in seen:
            seen.add(fn)
            files.append((fn, code))

    # Pattern 3: Top-line comment in code block with file path (e.g. "// lib/main.dart" or "# app/models.py")
    p3 = re.compile(
        r'```(?:\w+)?\n(?://|#|/\*|<!--)\s*([a-zA-Z0-9_\-\./\\]+\.' + exts + r')[^\n]*\n(.*?)```',
        re.DOTALL
    )
    for match in p3.finditer(content):
        fn = match.group(1).strip().lstrip('/')
        code = match.group(2).strip()
        if fn not in seen:
            seen.add(fn)
            files.append((fn, code))

    return files


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

def styleguide_view(request):
    return render(request, 'styleguide.html')

def welcome_view(request):
    return render(request, 'welcome.html')

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
    history = list(messages_list.values('role', 'content'))
    
    completeness_score = 0
    rubric_cats = {}
    if history:
        try:
            eval_res = CompletenessEngine.evaluate_rubric(history)
            completeness_score = eval_res.get('score', 0)
            rubric_cats = eval_res.get('categories', {})
        except Exception:
            completeness_score = CompletenessEngine._calculate_keyword_fallback_score(history)
            
    return render(request, 'chat.html', {
        'session': session,
        'chat_messages': messages_list,
        'generated_codes': codes,
        'today_sessions': today_sessions,
        'yesterday_sessions': yesterday_sessions,
        'last_7_days_sessions': last_7_days_sessions,
        'older_sessions': older_sessions,
        'is_first_load': is_first_load,
        'completeness_score': completeness_score,
        'rubric_cats': rubric_cats,
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
        user_words = set(re.findall(r'\b\w+\b', confirmation_msg))
        is_approval = any(w in user_words for w in ['yes', 'y', 'proceed', 'generate', 'approve', 'build', 'ok', 'sure'])
        
        if session.mode == 'mode1':
            if session.status == 'completed' or session.generated_codes.exists():
                edit_triggers = ['modify', 'update', 'change', 'refactor', 'edit', 'rewrite', 'fix code', 'add field', 'add model', 'fix bug']
                wants_edit = any(trig in user_content.lower() for trig in edit_triggers)
                existing_codes = list(session.generated_codes.all())
                
                if wants_edit and existing_codes:
                    target_mod = existing_codes[-1]
                    for mod in existing_codes:
                        if mod.module_name.lower() in user_content.lower():
                            target_mod = mod
                            break
                    summary = SRSSynthesizer.synthesize_summary(history, provider_name=provider_name)
                    updated_code = CodeBuilder.generate_code_for_module(target_mod.module_name, summary, modifications=user_content, provider_name=provider_name)
                    target_mod.code_content = updated_code
                    target_mod.save()
                    response_text = f"### ✏️ Updated Module `{target_mod.module_name}`\n\nI have updated `{target_mod.module_name}` based on your request. You can inspect the updated code in the right panel and download the project ZIP."
                else:
                    summary = SRSSynthesizer.synthesize_summary(history, provider_name=provider_name)
                    post_prompt = (
                        f"Project Specification:\n{summary}\n\n"
                        f"User Question: \"{user_content}\"\n\n"
                        "The user's project codebase has already been generated and packaged into a ZIP. "
                        "Answer their question directly with clear, practical steps (e.g., exact commands to run the project, how to open in an IDE like VS Code or PyCharm, how to start the development server, how to access admin, etc.)."
                    )
                    post_system = (
                        "You are DevDialogue AI — Lead Systems Architect. "
                        "Guide the user on running, testing, or understanding their generated project clearly, step-by-step, with practical terminal commands and IDE instructions."
                    )
                    response_text = LLMRouter.generate(prompt=post_prompt, system_prompt=post_system, provider_name=provider_name)
            elif is_approval:
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
                    "I have generated the complete codebase based on your requirements. You can inspect the code in the right panel and download the turnkey project ZIP."
                )
            else:
                response_text = InterviewerService.generate_next_question(history, provider_name=provider_name)
        else:
            # Mode 2: Incremental Module-by-Module Generation
            summary = SRSSynthesizer.synthesize_summary(history, provider_name=provider_name)
            modules = FilePlanner.get_module_list(summary)
            existing_codes = list(session.generated_codes.all())
            
            # Check if all modules have already been generated and approved
            if session.status == 'completed' or (len(existing_codes) >= len(modules) and len(modules) > 0):
                edit_triggers = ['modify', 'update', 'change', 'refactor', 'edit', 'rewrite', 'fix code', 'add field', 'add model', 'fix bug']
                wants_edit = any(trig in user_content.lower() for trig in edit_triggers)
                
                if wants_edit and existing_codes:
                    target_mod = existing_codes[-1]
                    for mod in existing_codes:
                        if mod.module_name.lower() in user_content.lower():
                            target_mod = mod
                            break
                    updated_code = CodeBuilder.generate_code_for_module(
                        target_mod.module_name,
                        summary,
                        modifications=user_content,
                        provider_name=provider_name
                    )
                    target_mod.code_content = updated_code
                    target_mod.save()
                    response_text = (
                        f"### ✏️ Updated Module `{target_mod.module_name}`\n\n"
                        f"I have modified `{target_mod.module_name}` based on your request: *\"{user_content}\"*\n\n"
                        f"You can review the updated code in the right panel and download the project ZIP anytime."
                    )
                else:
                    # User is asking a post-generation question (e.g. "Okay now how to run it")
                    post_prompt = (
                        f"Project Specification:\n{summary}\n\n"
                        f"User Question: \"{user_content}\"\n\n"
                        "The user's project codebase has already been generated and packaged into a ZIP. "
                        "Answer their question directly with clear, practical steps (e.g., exact commands to run the project, how to open in an IDE like VS Code or PyCharm, how to start the development server, how to access admin, etc.)."
                    )
                    post_system = (
                        "You are DevDialogue AI — Lead Systems Architect. "
                        "Guide the user on running, testing, or understanding their generated project clearly, step-by-step, with practical terminal commands and IDE instructions."
                    )
                    response_text = LLMRouter.generate(prompt=post_prompt, system_prompt=post_system, provider_name=provider_name)
            elif len(existing_codes) > 0 and not is_approval:
                # User wants to modify the current module based on feedback during review
                last_mod = existing_codes[-1]
                updated_code = CodeBuilder.generate_code_for_module(
                    last_mod.module_name, 
                    summary, 
                    modifications=user_content, 
                    provider_name=provider_name
                )
                last_mod.code_content = updated_code
                last_mod.save()
                
                response_text = (
                    f"### ✏️ Updated Module `{last_mod.module_name}`\n\n"
                    f"I have modified `{last_mod.module_name}` based on your feedback: *\"{user_content}\"*\n\n"
                    f"You can inspect the updated code in the right panel. Do you approve this module? (Say **yes** to approve and proceed, or specify further changes)."
                )
            else:
                # User approved or starting next module
                if len(existing_codes) < len(modules):
                    current_mod = modules[len(existing_codes)]
                    code = CodeBuilder.generate_code_for_module(current_mod, summary, provider_name=provider_name)
                    GeneratedCode.objects.create(session=session, module_name=current_mod, code_content=code)
                    
                    response_text = (
                        f"### Module {len(existing_codes)+1}/{len(modules)}: `{current_mod}`\n\n"
                        f"I have generated the code for `{current_mod}`. Inspect it in the right panel.\n\n"
                        f"Do you approve this module? (Say **yes** to move to the next module, or describe what changes you want)."
                    )
                else:
                    session.status = 'completed'
                    session.save()
                    response_text = "### 🚀 Incremental Generation Complete!\nAll project modules have been approved and generated. You can download the complete project ZIP from the sidebar."
    else:
        # Check if user explicitly demanded code/files or agreed to generation prompt
        code_demand_triggers = [
            "provide me all files", "provide all files", "give me all files", "give me the files",
            "don't ask more questions", "no more questions", "all files at once", "give me the code",
            "give code", "generate files", "just code", "stop asking questions"
        ]
        is_direct_code_demand = any(trig in user_content.lower() for trig in code_demand_triggers)

        # Also detect if assistant previously offered to generate files and user said yes/sure
        if not is_direct_code_demand and assist_msgs:
            last_assist_text = assist_msgs[-1]['content'].lower()
            asked_to_proceed = any(p in last_assist_text for p in [
                "proceed", "generate the files", "generate the complete", "ready to proceed", 
                "generate your", "shall i generate", "should i proceed", "bring this architecture"
            ])
            user_words = set(re.findall(r'\b\w+\b', user_content.lower()))
            if asked_to_proceed and any(w in user_words for w in ['sure', 'yes', 'yup', 'yeah', 'ok', 'okay', 'proceed', 'build', 'generate', 'go ahead']):
                is_direct_code_demand = True

        historical_files = []
        for m in assist_msgs:
            historical_files.extend(extract_code_files_from_markdown(m['content']))

        if is_direct_code_demand and historical_files:
            for fn, code_content in historical_files:
                obj, _ = GeneratedCode.objects.get_or_create(session=session, module_name=fn)
                obj.code_content = code_content
                obj.save()
            session.status = 'completed'
            session.save(update_fields=['status'])
            response_text = (
                "### 🎉 Complete Project Codebase Ready!\n\n"
                "I have loaded all generated codebase files into your **Workspace File Tree** on the right.\n\n"
                "You can inspect each file in the editor tabs and download the complete turnkey project anytime via **Export ZIP**."
            )
        elif is_direct_code_demand:
            summary = SRSSynthesizer.synthesize_summary(history, provider_name=provider_name)
            modules = FilePlanner.get_module_list(summary)
            for mod in modules:
                if not session.generated_codes.filter(module_name=mod).exists():
                    code = CodeBuilder.generate_code_for_module(mod, summary, provider_name=provider_name)
                    GeneratedCode.objects.create(session=session, module_name=mod, code_content=code)
            session.status = 'completed'
            session.save(update_fields=['status'])
            response_text = (
                "### 🎉 All Project Files Generated!\n\n"
                "I have generated the complete codebase for your application. You can view all files in the right panel and download the turnkey project ZIP."
            )
        elif CompletenessEngine.should_synthesize_summary(history, user_content, provider_name=provider_name):
            response_text = SRSSynthesizer.synthesize_summary(history, is_mode2=(session.mode == 'mode2'), provider_name=provider_name)
        else:
            response_text = InterviewerService.generate_next_question(history, provider_name=provider_name)
                
    # Auto-extract any code blocks outputted in the assistant's response directly into GeneratedCode
    newly_extracted = extract_code_files_from_markdown(response_text)
    if newly_extracted:
        for fn, code_content in newly_extracted:
            obj, _ = GeneratedCode.objects.get_or_create(session=session, module_name=fn)
            obj.code_content = code_content
            obj.save()
        session.status = 'completed'
        session.save(update_fields=['status'])

        # Clean up response_text so it does not dump raw code in the chat window
        file_bullets = "\n".join([f"- 📄 `{fn}`" for fn, _ in newly_extracted])
        response_text = (
            "### 🎉 Project Codebase Generated!\n\n"
            "I have generated and packaged your project files directly into the **Workspace File Tree** on the right:\n\n"
            f"{file_bullets}\n\n"
            "You can inspect each file in the editor tabs and download your complete turnkey project anytime via **Export ZIP**."
        )

    Message.objects.create(session=session, role='assistant', content=response_text)

    
    if not session.has_custom_title:
        new_title = generate_title_from_user_msg(user_content)
        if new_title != "New Chat":
            session.title = new_title
            session.has_custom_title = True
            session.save()
        
    codes = list(session.generated_codes.values('id', 'module_name'))
    
    # Calculate live updated completeness score & categories
    try:
        updated_eval = CompletenessEngine.evaluate_rubric(history)
        comp_score = updated_eval.get('score', 0)
        rubric_cats = updated_eval.get('categories', {})
    except Exception:
        comp_score = CompletenessEngine._calculate_keyword_fallback_score(history)
        rubric_cats = {}

    return JsonResponse({
        'response': response_text,
        'status': session.status,
        'codes': codes,
        'title': session.title,
        'completeness_score': comp_score,
        'rubric_cats': rubric_cats
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

@verification_required
def get_job_events_api(request, job_id):
    from chat.models import Job
    job = get_object_or_404(Job, id=job_id, user=request.user)
    
    after_seq = int(request.GET.get('after', 0))
    events = list(job.events.filter(sequence_number__gt=after_seq).values(
        'sequence_number', 'kind', 'message', 'data', 'created_at'
    ))
    
    return JsonResponse({
        'job_id': job.id,
        'status': job.status,
        'progress_current': job.progress_current,
        'progress_total': job.progress_total,
        'result_summary': job.result_summary,
        'error_message': job.error_message,
        'cancel_requested': job.cancel_requested,
        'events': events
    })

@verification_required
def cancel_job_api(request, job_id):
    from chat.models import Job
    if request.method == 'POST':
        job = get_object_or_404(Job, id=job_id, user=request.user)
        job.cancel_requested = True
        job.save(update_fields=['cancel_requested'])
        return JsonResponse({'status': 'cancellation_requested', 'job_id': job.id})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=400)

@verification_required
def get_plan_api(request, session_id):
    from chat.models import ProjectPlan
    session = get_object_or_404(Session, id=session_id, user=request.user)
    plan = session.plans.order_by('-version').first()
    if not plan:
        return JsonResponse({'has_plan': False})
    return JsonResponse({
        'has_plan': True,
        'id': plan.id,
        'version': plan.version,
        'status': plan.status,
        'plan_data': plan.plan_data,
        'generation_order': plan.generation_order
    })

@verification_required
def get_verification_api(request, session_id):
    from chat.models import VerificationRun
    session = get_object_or_404(Session, id=session_id, user=request.user)
    verif = session.verification_runs.order_by('-created_at').first()
    if not verif:
        return JsonResponse({'has_verification': False})
    return JsonResponse({
        'has_verification': True,
        'level': verif.level,
        'passed': verif.passed,
        'error_count': verif.error_count,
        'warning_count': verif.warning_count,
        'issues': verif.issues,
        'created_at': verif.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
    })

@verification_required
def get_file_tree_api(request, session_id):
    from chat.models import ProjectFile, GeneratedCode
    session = get_object_or_404(Session, id=session_id, user=request.user)
    p_files = list(session.project_files.values('id', 'path', 'status', 'current_version', 'updated_at'))
    g_codes = list(session.generated_codes.values('id', 'module_name'))
    
    return JsonResponse({
        'project_files': p_files,
        'generated_codes': g_codes
    })


