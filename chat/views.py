import json
import re
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.conf import settings

from accounts.decorators import verification_required
from chat.models import Session, Message, GeneratedCode, ProjectFile
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
    
    # ProjectFile is single source of truth; backfill if legacy GeneratedCode exists (#27)
    from chat.models import ProjectFile
    project_files = session.project_files.order_by('path')
    if not project_files.exists() and session.generated_codes.exists():
        for gc in session.generated_codes.all():
            ProjectFile.objects.get_or_create(session=session, path=gc.module_name, defaults={'content': gc.code_content, 'status': 'verified'})
        project_files = session.project_files.order_by('path')
    
    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    seven_days_ago = today_start - timedelta(days=7)
    
    all_sessions = Session.objects.filter(user=request.user).order_by('-started_at')
    
    today_sessions = [s for s in all_sessions if timezone.localtime(s.started_at) >= today_start]
    yesterday_sessions = [s for s in all_sessions if today_start > timezone.localtime(s.started_at) >= yesterday_start]
    last_7_days_sessions = [s for s in all_sessions if yesterday_start > timezone.localtime(s.started_at) >= seven_days_ago]
    older_sessions = [s for s in all_sessions if timezone.localtime(s.started_at) < seven_days_ago]
    
    is_first_load = messages_list.count() == 0
    history = list(messages_list.values('role', 'content'))
    
    if session.status in ('srs_ready', 'plan_draft', 'plan_approved', 'generating', 'ready', 'needs_attention', 'completed'):
        completeness_score = 100
    else:
        completeness_score = CompletenessEngine._calculate_keyword_fallback_score(history) if history else 0
    rubric_cats = {}
    
    active_job = session.jobs.filter(status__in=['queued', 'running']).order_by('-created_at').first()

    # Determine available AI providers for dropdown
    import os
    available_providers = ['auto', 'free']
    has_openai = bool(os.environ.get('OPENAI_API_KEY') or (hasattr(request.user, 'profile') and request.user.profile.get_openai_key()))
    has_gemini = bool(os.environ.get('GEMINI_API_KEY') or (hasattr(request.user, 'profile') and request.user.profile.get_gemini_key()))
    has_claude = bool(os.environ.get('ANTHROPIC_API_KEY'))
    has_deepseek = bool(os.environ.get('DEEPSEEK_API_KEY'))

    if has_gemini:
        available_providers.append('gemini')
    if has_openai:
        available_providers.append('openai')
    if has_claude:
        available_providers.append('claude')
    if has_deepseek:
        available_providers.append('deepseek')

    return render(request, 'chat.html', {
        'session': session,
        'chat_messages': messages_list,
        'project_files': project_files,
        'generated_codes': project_files,
        'today_sessions': today_sessions,
        'yesterday_sessions': yesterday_sessions,
        'last_7_days_sessions': last_7_days_sessions,
        'older_sessions': older_sessions,
        'is_first_load': is_first_load,
        'completeness_score': completeness_score,
        'rubric_cats': rubric_cats,
        'active_job': active_job,
        'available_providers': available_providers,
    })

def _run_job_worker(job_id, provider_name):
    from django.db import connection
    from generator.jobs import JobExecutionEngine
    from chat.models import Job
    try:
        j = JobExecutionEngine.run_job(job_id, provider_name=provider_name)
        j.refresh_from_db()
        sess = j.session
        sess.refresh_from_db()
        if j.status == 'failed':
            msg_text = (
                "### ⚠️ Codebase Generation Encountered an Issue\n\n"
                f"{j.error_message or 'The build engine encountered an error while generating project files.'}\n\n"
                "Please try again or request modifications to your requirements."
            )
        elif sess.status == 'needs_attention':
            msg_text = (
                "### ⚠️ Complete Project Codebase Ready (Verification Warnings Remain)\n\n"
                f"{j.result_summary or 'All project files have been planned and generated, but some static verification checks need attention.'}\n\n"
                "You can inspect each file in the workspace file tree on the right, view verification issues in the Checks panel, and download the project ZIP."
            )
        else:
            msg_text = (
                "### 🎉 Complete Project Codebase Ready!\n\n"
                f"{j.result_summary or 'All project files have been planned, generated, and verified.'}\n\n"
                "You can inspect each file in the workspace file tree on the right, view the architecture plan and verification checks, and download your turnkey project ZIP."
            )
        Message.objects.create(session=sess, role='assistant', content=msg_text)
    except Exception as worker_err:
        try:
            job_obj = Job.objects.filter(id=job_id).first()
            if job_obj:
                job_obj.status = 'failed'
                job_obj.error_message = str(worker_err)
                job_obj.save(update_fields=['status', 'error_message'])
                sess = job_obj.session
                if sess.status == 'generating':
                    sess.status = 'needs_attention'
                    sess.save(update_fields=['status'])
                Message.objects.create(
                    session=sess,
                    role='assistant',
                    content=f"### ⚠️ Generation Failed\n\nAn unexpected worker error occurred: {str(worker_err)}"
                )
        except Exception:
            pass
    finally:
        connection.close()


def _trigger_generation_job(session, user, provider_name, run_async=True):
    from generator.jobs import JobExecutionEngine
    job = JobExecutionEngine.create_job(session=session, user=user, job_type='generate')
    if run_async:
        import threading
        thread = threading.Thread(target=_run_job_worker, args=(job.id, provider_name), daemon=True)
        thread.start()
        response_text = (
            "### 🚀 Codebase Generation Started!\n\n"
            "I have started planning, generating, and verifying your project files in the background.\n\n"
            "You can watch real-time generation and static verification in the progress banner above. The workspace files will populate automatically as they complete."
        )
    else:
        JobExecutionEngine.run_job(job.id, provider_name=provider_name)
        job.refresh_from_db()
        session.refresh_from_db()
        if job.status == 'failed':
            response_text = (
                "### ⚠️ Codebase Generation Encountered an Issue\n\n"
                f"{job.error_message or 'The build engine encountered an error while generating project files.'}\n\n"
                "Please try again or request modifications to your requirements."
            )
        elif session.status == 'needs_attention':
            response_text = (
                "### ⚠️ Complete Project Codebase Ready (Verification Warnings Remain)\n\n"
                f"{job.result_summary or 'All project files have been planned and generated, but some static verification checks need attention.'}\n\n"
                "You can inspect each file in the workspace file tree on the right, view the architecture plan and verification checks, and download your turnkey project ZIP."
            )
        else:
            response_text = (
                "### 🎉 Complete Project Codebase Ready!\n\n"
                f"{job.result_summary or 'All project files have been planned, generated, and verified.'}\n\n"
                "You can inspect each file in the workspace file tree on the right, view the architecture plan and verification checks, and download your turnkey project ZIP."
            )
    return job, response_text


def _handle_module_edit(session, user_content, summary, existing_files, provider_name, user):
    target_pf = existing_files[-1]
    for pf in existing_files:
        if pf.path.lower() in user_content.lower():
            target_pf = pf
            break
    updated_code = CodeBuilder.generate_code_for_module(
        target_pf.path,
        summary,
        modifications=user_content,
        provider_name=provider_name,
        session=session,
        user=user
    )
    target_pf.create_new_version(updated_code, source='user_feedback')

    from generator.verifier import StaticVerifier
    from chat.models import VerificationRun
    files_dict = {f.path: f.content for f in session.project_files.all()}
    verif_res = StaticVerifier.verify_project(files_dict)
    VerificationRun.objects.create(
        session=session,
        level='static',
        passed=verif_res.get('passed', True),
        error_count=verif_res.get('error_count', 0),
        warning_count=verif_res.get('warning_count', 0),
        issues=verif_res.get('issues', [])
    )
    file_issues = {iss['file'] for iss in verif_res.get('issues', [])}
    target_pf.status = 'has_issues' if target_pf.path in file_issues else 'verified'
    target_pf.save(update_fields=['status'])

    verif_msg = ""
    if not verif_res.get('passed', True):
        verif_msg = f"\n\n*Note: Static verification reported {verif_res.get('error_count', 0)} issue(s). Check the Verification panel for details.*"

    return (
        f"### ✏️ Updated Module `{target_pf.path}`\n\n"
        f"I have modified `{target_pf.path}` based on your request: *\"{user_content}\"*\n\n"
        f"You can review the updated code in the right panel and download the project ZIP anytime.{verif_msg}"
    )


def _handle_post_generation_qa(session, user_content, summary, provider_name, user):
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
    return LLMRouter.generate(prompt=post_prompt, system_prompt=post_system, provider_name=provider_name, purpose='chat', session=session, user=user)


def _complete_incremental_project(session, plan_obj, provider_name):
    from generator.repair import CodeRepairEngine
    from chat.state_machine import SessionStateMachine

    all_files_dict = {pf.path: pf.content for pf in session.project_files.all()}
    repair_res = CodeRepairEngine.run_repair_loop(
        session=session,
        files_dict=all_files_dict,
        plan_data=plan_obj.plan_data if plan_obj else None,
        max_attempts=3,
        provider_name=provider_name
    )
    if repair_res.get('status') in ('verified', 'verified_with_warnings'):
        SessionStateMachine.transition_to(session, 'ready')
    else:
        SessionStateMachine.transition_to(session, 'needs_attention')

    return (
        f"### 🚀 Incremental Generation Complete!\n\n"
        f"{repair_res.get('honest_message', 'All project files have been planned, generated, and verified.')}\n\n"
        "All project modules have been approved and generated. You can download the complete project ZIP from the sidebar."
    )


def _generate_next_module(session, user, provider_name, summary=None, modules=None, existing_files=None):
    from chat.state_machine import SessionStateMachine
    from generator.planner import PlanGenerator

    if not summary:
        history = list(session.messages.values('role', 'content'))
        summary = session.summary_text or SRSSynthesizer.synthesize_summary(history, is_mode2=True, provider_name=provider_name, session=session, user=user)
        session.summary_text = summary
        session.save(update_fields=['summary_text'])
        SessionStateMachine.transition_to(session, 'srs_ready')

    plan_obj = session.plans.first()
    if not plan_obj and summary:
        try:
            plan_obj = PlanGenerator.generate_plan(summary, session, provider_name=provider_name)
        except Exception:
            plan_obj = None

    if modules is None:
        modules = plan_obj.generation_order if plan_obj else FilePlanner.get_module_list(summary)

    if not modules:
        return None, 0, 0, "I couldn't determine the module list for your project. Please provide more details about your requirements."

    if existing_files is None:
        existing_files = list(session.project_files.filter(path__in=modules))

    generated_paths = set(pf.path for pf in existing_files)
    remaining = [m for m in modules if m not in generated_paths]

    if not remaining:
        return None, len(modules), len(modules), ""

    current_mod = remaining[0]
    module_num = len(modules) - len(remaining) + 1
    existing_files_dict = {pf.path: pf.content for pf in existing_files}

    code = CodeBuilder.generate_code_for_module(
        current_mod,
        summary,
        all_files=modules,
        existing_files=existing_files_dict,
        provider_name=provider_name,
        session=session,
        user=user
    )
    ProjectFile.objects.create(session=session, path=current_mod, content=code, status='generated')

    if session.status != 'generating':
        SessionStateMachine.transition_to(session, 'generating')

    msg = (
        f"### Module {module_num}/{len(modules)}: `{current_mod}`\n\n"
        f"I have generated the code for `{current_mod}`. Inspect it in the right panel.\n\n"
        f"Do you approve this module? (Say **yes** to move to the next module, or describe what changes you want)."
    )
    return current_mod, module_num, len(modules), msg


def _handle_mode1_message(session, user_content, action, is_approval, provider_name, run_async, history, user):
    existing_files = list(session.project_files.all())
    if session.status in ('completed', 'ready', 'needs_attention') or bool(existing_files):
        edit_patterns = [
            r'\b(modify|update|refactor|rewrite|edit|fix code|add field|add model|fix bug)\b',
            r'\bchange\s+(the\s+)?(code|module|file|function|class|model|view|schema|implementation)\b'
        ]
        wants_edit = (action == 'edit') or any(re.search(pat, user_content, re.IGNORECASE) for pat in edit_patterns)
        summary = session.summary_text or SRSSynthesizer.synthesize_summary(history, provider_name=provider_name, session=session, user=user)
        if wants_edit and existing_files:
            return None, _handle_module_edit(session, user_content, summary, existing_files, provider_name, user)
        else:
            return None, _handle_post_generation_qa(session, user_content, summary, provider_name, user)
    elif is_approval:
        active_job, resp_text = _trigger_generation_job(session, user, provider_name, run_async=run_async)
        return active_job, resp_text
    else:
        return None, InterviewerService.generate_next_question(history, provider_name=provider_name, session=session, user=user)


def _handle_mode2_message(session, user_content, action, is_approval, provider_name, history, user):
    summary = session.summary_text or SRSSynthesizer.synthesize_summary(history, is_mode2=True, provider_name=provider_name, session=session, user=user)
    from generator.planner import PlanGenerator
    plan_obj = session.plans.first()
    if not plan_obj and summary:
        try:
            plan_obj = PlanGenerator.generate_plan(summary, session, provider_name=provider_name)
        except Exception:
            plan_obj = None

    modules = plan_obj.generation_order if plan_obj else FilePlanner.get_module_list(summary)
    existing_files = list(session.project_files.filter(path__in=modules))
    all_modules_generated = len(existing_files) >= len(modules) and len(modules) > 0

    edit_patterns = [
        r'\b(modify|update|refactor|rewrite|edit|fix code|add field|add model|fix bug)\b',
        r'\bchange\s+(the\s+)?(code|module|file|function|class|model|view|schema|implementation)\b'
    ]
    wants_edit = (action == 'edit') or any(re.search(pat, user_content, re.IGNORECASE) for pat in edit_patterns)

    # 1. Project already completed and verified
    if session.status in ('completed', 'ready', 'needs_attention'):
        if wants_edit and existing_files:
            return _handle_module_edit(session, user_content, summary, existing_files, provider_name, user)
        else:
            return _handle_post_generation_qa(session, user_content, summary, provider_name, user)

    # 2. All planned modules exist: awaiting final approval/completion
    if all_modules_generated:
        if wants_edit and existing_files:
            return _handle_module_edit(session, user_content, summary, existing_files, provider_name, user)
        else:
            # User approved or confirmed the final module -> run completion & verification!
            return _complete_incremental_project(session, plan_obj, provider_name)

    # 3. Intermediate module review: user requests changes to current module
    if len(existing_files) > 0 and not is_approval:
        last_pf = existing_files[-1]
        updated_code = CodeBuilder.generate_code_for_module(
            last_pf.path,
            summary,
            modifications=user_content,
            provider_name=provider_name,
            session=session,
            user=user
        )
        last_pf.create_new_version(updated_code, source='user_feedback')
        return (
            f"### ✏️ Updated Module `{last_pf.path}`\n\n"
            f"I have modified `{last_pf.path}` based on your feedback: *\"{user_content}\"*\n\n"
            f"You can inspect the updated code in the right panel. Do you approve this module? (Say **yes** to approve and proceed, or specify further changes)."
        )

    # 4. User approved or starting next module
    _, _, _, response_text = _generate_next_module(
        session=session,
        user=user,
        provider_name=provider_name,
        summary=summary,
        modules=modules,
        existing_files=existing_files
    )
    return response_text


@verification_required
def send_message_api(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)
        
    session = get_object_or_404(Session, id=session_id, user=request.user)
    active_job = None
    if request.headers.get('X-Run-Sync') == 'false':
        run_async = True
    elif request.headers.get('X-Run-Sync') == 'true' or request.GET.get('sync') == '1':
        run_async = False
    else:
        run_async = not getattr(settings, 'IS_TESTING', False)
        
    try:
        data = json.loads(request.body)
        user_content = data.get('message', '').strip()
        provider_name = data.get('provider', None)
        action = data.get('action', None)
        req_id = data.get('request_id', None)
    except Exception:
        user_content = request.POST.get('message', '').strip()
        provider_name = None
        action = request.POST.get('action', None)
        req_id = request.POST.get('request_id', None)
        
    if not user_content:
        return JsonResponse({'error': 'Message content cannot be empty'}, status=400)
        
    from django.core.cache import cache
    # Clear any old session cancellation flag so future messages are never swallowed (#2)
    cache.delete(f"cancel_session_{session.id}")

    Message.objects.create(session=session, role='user', content=user_content)
    history = list(session.messages.values('role', 'content'))
    
    # Legacy migration: ensure ProjectFile rows exist if only GeneratedCode exists
    if not session.project_files.exists() and session.generated_codes.exists():
        for gc in session.generated_codes.all():
            ProjectFile.objects.get_or_create(session=session, path=gc.module_name, defaults={'content': gc.code_content, 'status': 'verified'})
    
    from chat.state_machine import SessionStateMachine
    from generator.jobs import JobConcurrencyError
    from llm_engine.router import UsageLimitExceededError

    try:
        user_msgs = [m for m in history if m['role'] == 'user']
        assist_msgs = [m for m in history if m['role'] == 'assistant']
        
        response_text = ""
        is_direct_code_demand = False
        has_summary = any(
            re.search(r'#+\s*(?:Project\s+)?Requirements\s+Summary', m['content'], re.IGNORECASE)
            for m in assist_msgs
        ) or bool(session.summary_text) or session.status in ('srs_ready', 'plan_draft', 'plan_approved', 'generating', 'ready', 'needs_attention', 'completed')
        
        if has_summary:
            is_approval = False
            if action == 'generate':
                is_approval = True
            else:
                confirmation_msg = user_content.lower().strip()
                has_negation = bool(re.search(r'\b(no|not|don\'?t|never|wait|stop|hold|cancel|refuse)\b', confirmation_msg))
                if not has_negation:
                    # Strict affirmative match: user's input is a dedicated approval command or affirmative phrase
                    strict_approval_patterns = [
                        r'^(yes|y|proceed|approve|confirm|ok|okay|sure|go ahead|looks good|looks great|lgtm|perfect|fine|accepted|approved)[.!]?$',
                        r'^(proceed|start|begin|go ahead)\s+(with\s+)?(generation|code|building|all files|project)[.!]?$',
                        r'^(generate|build)\s+(the\s+)?(code|files|codebase|project|all files)[.!]?$',
                        r'^(yes|sure|okay|yep|yup)[,\s]+(please\s+)?(proceed|generate|build|start|go ahead)(\s+(and|&)\s+(generate|build|proceed))?(\s+(with\s+)?(it|code|generation|the files|files|all files|the codebase|project))?[.!]?$',
                        r'^proceed with code generation and build all project files[.!]?$'
                    ]
                    if any(re.match(pat, confirmation_msg) for pat in strict_approval_patterns):
                        is_approval = True

            if session.mode == 'mode1':
                active_job, response_text = _handle_mode1_message(session, user_content, action, is_approval, provider_name, run_async, history, request.user)
            else:
                response_text = _handle_mode2_message(session, user_content, action, is_approval, provider_name, history, request.user)
        else:
            # Check if user explicitly demanded code/files or agreed to generation prompt
            code_demand_triggers = [
                "provide me all files", "provide all files", "give me all files", "give me the files",
                "don't ask more questions", "no more questions", "all files at once", "give me the code",
                "give code", "generate files", "just code", "stop asking questions"
            ]
            is_direct_code_demand = any(trig in user_content.lower() for trig in code_demand_triggers)

            if not is_direct_code_demand and assist_msgs:
                last_assist_text = assist_msgs[-1]['content'].lower()
                asked_to_proceed = any(p in last_assist_text for p in [
                    "proceed", "generate the files", "generate the complete", "ready to proceed", 
                    "generate your", "shall i generate", "should i proceed", "bring this architecture"
                ])
                user_words = set(re.findall(r'\b\w+\b', user_content.lower()))
                if asked_to_proceed and any(w in user_words for w in ['sure', 'yes', 'yup', 'yeah', 'ok', 'okay', 'proceed', 'build', 'generate', 'go ahead']):
                    is_direct_code_demand = True

            if is_direct_code_demand:
                if session.mode == 'mode2':
                    _, _, _, response_text = _generate_next_module(session=session, user=request.user, provider_name=provider_name)
                else:
                    active_job, response_text = _trigger_generation_job(session, request.user, provider_name, run_async=run_async)
            elif CompletenessEngine.should_synthesize_summary(history, user_content, provider_name=provider_name):
                response_text = SRSSynthesizer.synthesize_summary(history, is_mode2=(session.mode == 'mode2'), provider_name=provider_name, session=session, user=request.user)
                session.summary_text = response_text
                session.save(update_fields=['summary_text'])
                SessionStateMachine.transition_to(session, 'srs_ready')
            else:
                response_text = InterviewerService.generate_next_question(history, provider_name=provider_name, session=session, user=request.user)
    except JobConcurrencyError:
        return JsonResponse({
            'error': 'A generation job is already active for this session. Please wait for it to complete.',
            'status': session.status
        }, status=409)
    except UsageLimitExceededError as ule:
        return JsonResponse({
            'error': str(ule),
            'status': session.status
        }, status=429)
    except RuntimeError as rerr:
        err_msg = "⚠️ The AI service is temporarily unavailable or experiencing high traffic. Please try sending your message again in a few moments."
        Message.objects.create(session=session, role='assistant', content=err_msg)
        return JsonResponse({
            'error': str(rerr),
            'response': err_msg,
            'status': session.status
        }, status=503)
    except Exception as gen_err:
        import logging
        logging.getLogger(__name__).exception("Unhandled exception in send_message_api")
        err_msg = "⚠️ An unexpected server error occurred while processing your message. Please try again."
        Message.objects.create(session=session, role='assistant', content=err_msg)
        return JsonResponse({
            'error': str(gen_err),
            'response': err_msg,
            'status': session.status
        }, status=500)

    from django.core.cache import cache
    is_cancelled = False
    if req_id and cache.get(f"cancel_req_{req_id}"):
        is_cancelled = True
        cache.delete(f"cancel_req_{req_id}")
    elif cache.get(f"cancel_session_{session.id}"):
        is_cancelled = True
        cache.delete(f"cancel_session_{session.id}")

    if is_cancelled:
        return JsonResponse({
            'cancelled': True,
            'response': '⚠️ Message generation was cancelled by user.',
            'status': session.status
        })

    Message.objects.create(session=session, role='assistant', content=response_text)

    
    if not session.has_custom_title:
        new_title = generate_title_from_user_msg(user_content)
        if new_title != "New Chat":
            session.title = new_title
            session.has_custom_title = True
            session.save()
        
    codes = [{'id': f.id, 'module_name': f.path} for f in session.project_files.order_by('path')]
    
    # Calculate live updated completeness score & categories
    if session.status in ('srs_ready', 'plan_draft', 'plan_approved', 'generating', 'ready', 'needs_attention', 'completed'):
        comp_score = 100
        rubric_cats = {
            'Core Functionality & Flow': 'Complete',
            'Data & Architecture': 'Complete',
            'Authentication & Security': 'Complete',
            'UI & Integration': 'Complete'
        }
    else:
        try:
            updated_eval = CompletenessEngine.evaluate_rubric(history, provider_name=provider_name)
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
        'rubric_cats': rubric_cats,
        'job_id': active_job.id if active_job else None
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
    from chat.models import ProjectFile
    pf = get_object_or_404(ProjectFile, id=code_id, session__user=request.user)
    return JsonResponse({
        'module_name': pf.path,
        'code_content': pf.content,
        'version': pf.current_version,
        'status': pf.status
    })

@verification_required
def get_job_events_api(request, job_id):
    from chat.models import Job
    job = get_object_or_404(Job, id=job_id, user=request.user)
    
    try:
        after_seq = int(request.GET.get('after', 0))
    except (ValueError, TypeError):
        after_seq = 0

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
        'session_status': job.session.status,
        'events': events
    })

@verification_required
def cancel_job_api(request, job_id):
    from django.utils import timezone
    from chat.models import Job
    if request.method == 'POST':
        job = get_object_or_404(Job, id=job_id, user=request.user)
        job.cancel_requested = True
        job.updated_at = timezone.now()
        if job.status == 'queued':
            job.status = 'cancelled'
            job.save(update_fields=['cancel_requested', 'status', 'updated_at'])
            job.log_event('info', "Job cancelled while queued.")
            if job.session.status == 'generating':
                job.session.status = 'srs_ready'
                job.session.save(update_fields=['status'])
        else:
            job.save(update_fields=['cancel_requested', 'updated_at'])
        return JsonResponse({'status': 'cancellation_requested', 'job_id': job.id})
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=400)

@verification_required
def cancel_session_api(request, session_id):
    from django.core.cache import cache
    from django.utils import timezone
    session = get_object_or_404(Session, id=session_id, user=request.user)
    
    # Specific per-request cancellation (#2)
    request_id = None
    if request.body:
        try:
            data = json.loads(request.body)
            request_id = data.get('request_id')
        except Exception:
            request_id = request.POST.get('request_id')
    if request_id:
        cache.set(f"cancel_req_{request_id}", True, 300)

    active_jobs = session.jobs.filter(status__in=['queued', 'running'])
    for j in active_jobs:
        j.cancel_requested = True
        j.updated_at = timezone.now()
        if j.status == 'queued':
            j.status = 'cancelled'
            j.save(update_fields=['cancel_requested', 'status', 'updated_at'])
        else:
            j.save(update_fields=['cancel_requested', 'updated_at'])
            
    if session.status == 'generating':
        session.status = 'srs_ready'
        session.save(update_fields=['status'])
        
    return JsonResponse({'status': 'cancelled', 'session_id': session.id})

@verification_required
def update_session_mode_api(request, session_id):
    session = get_object_or_404(Session, id=session_id, user=request.user)
    if request.method == 'POST':
        # Lock mode switching if generation has started or files exist
        if session.status not in ('active', 'interviewing') or session.project_files.exists() or session.jobs.filter(status__in=['running', 'queued', 'succeeded']).exists():
            return JsonResponse({'error': 'Mode cannot be changed once generation has started or files exist.'}, status=400)
        try:
            data = json.loads(request.body)
            new_mode = data.get('mode')
        except Exception:
            new_mode = request.POST.get('mode')
        if new_mode in ('mode1', 'mode2'):
            session.mode = new_mode
        else:
            session.mode = 'mode2' if session.mode == 'mode1' else 'mode1'
        session.save(update_fields=['mode'])
        return JsonResponse({'status': 'success', 'mode': session.mode})
    return JsonResponse({'error': 'POST required'}, status=400)

@verification_required
def approve_plan_api(request, session_id):
    from chat.models import ProjectPlan
    from chat.state_machine import SessionStateMachine
    if request.method == 'POST':
        session = get_object_or_404(Session, id=session_id, user=request.user)
        plan = session.plans.order_by('-version').first()
        if not plan:
            return JsonResponse({'error': 'No plan found for this session'}, status=404)
        plan.status = 'approved'
        plan.save(update_fields=['status'])
        try:
            SessionStateMachine.transition_to(session, 'plan_approved')
        except Exception as e:
            return JsonResponse({'error': f"Cannot transition state: {str(e)}"}, status=400)
        return JsonResponse({'status': 'approved', 'plan_id': plan.id, 'version': plan.version})
    return JsonResponse({'error': 'POST required'}, status=400)

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
    from chat.models import ProjectFile
    session = get_object_or_404(Session, id=session_id, user=request.user)
    p_files = list(session.project_files.order_by('path').values('id', 'path', 'status', 'current_version', 'updated_at'))
    
    return JsonResponse({
        'project_files': p_files,
        'generated_codes': [{'id': f['id'], 'module_name': f['path']} for f in p_files]
    })


