import json
import logging
import os
import re
import uuid
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse, Http404
from django.utils import timezone
from django.conf import settings
from django.db import models

logger = logging.getLogger('chat.views')

def _get_session(session_id, user, select_related=None, prefetch_related=None):
    """
    Retrieves a Session for the user by UUID or by integer ID (for backwards compatibility).
    """
    qs = Session.objects
    if select_related:
        qs = qs.select_related(*select_related)
    if prefetch_related:
        qs = qs.prefetch_related(*prefetch_related)

    is_uuid = False
    if isinstance(session_id, uuid.UUID):
        is_uuid = True
    else:
        try:
            uuid.UUID(str(session_id))
            is_uuid = True
        except (ValueError, AttributeError):
            is_uuid = False

    if is_uuid:
        return get_object_or_404(qs, uuid=session_id, user=user)
    else:
        try:
            return get_object_or_404(qs, id=int(session_id), user=user)
        except (ValueError, TypeError):
            raise Http404("Session not found")

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
    sessions = request.user.sessions.all().only('id', 'uuid', 'mode', 'title', 'started_at', 'status', 'user_id').order_by('-started_at')
    profile = getattr(request, '_cached_profile', None) or request.user.profile
    return render(request, 'dashboard.html', {'sessions': sessions, 'profile': profile})

@verification_required
def new_chat_view(request):
    unused_session = (
        Session.objects.filter(user=request.user, status='active')
        .annotate(msg_count=models.Count('messages'))
        .filter(msg_count=0)
        .first()
    )
    if unused_session:
        logger.info("[NEW CHAT] Redirecting %s to existing empty Session #%s (%s)", request.user, unused_session.id, unused_session.uuid)
        return redirect('chat', session_id=unused_session.uuid)

    session = Session.objects.create(user=request.user, mode='mode1', status='active')
    logger.info("[NEW CHAT] Created fresh Session #%s (%s) for %s", session.id, session.uuid, request.user)
    return redirect('chat', session_id=session.uuid)

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
            status='ready' if mode == 'mode3' else 'active',
            title=generate_title_from_user_msg(description),
            has_custom_title=True
        )
        logger.info("[CREATE SESSION] Created Session #%s '%s' for %s (mode: %s)", session.id, session.title, request.user, mode)
        
        Message.objects.create(session=session, role='user', content=description)
        history = list(session.messages.values('role', 'content'))
        if mode == 'mode3':
            _, response_text = _handle_mode3_message(session, description, None, None, history, request.user)
            Message.objects.create(session=session, role='assistant', content=response_text)
            extracted = extract_code_files_from_markdown(response_text)
            for fn, code_c in extracted:
                pf, _ = ProjectFile.objects.get_or_create(session=session, path=fn, defaults={'content': code_c, 'status': 'verified'})
                if pf.content != code_c:
                    pf.create_new_version(code_c, source='generator')
        else:
            first_q = InterviewerService.generate_next_question(history)
            Message.objects.create(session=session, role='assistant', content=first_q)
        return redirect('chat', session_id=session.uuid)
    return redirect('dashboard')

@verification_required
def chat_view(request, session_id):
    session = _get_session(session_id, request.user, select_related=['user'])
    messages_list = session.messages.all().order_by('timestamp').prefetch_related('attachments')
    logger.info("[OPEN CHAT] Session #%s (%s) '%s' (status: %s) | %d messages | User: %s", session.id, session.uuid, session.title, session.status, messages_list.count(), request.user)
    
    # ProjectFile is single source of truth; backfill if legacy GeneratedCode exists (#27)
    from chat.models import ProjectFile
    project_files = session.project_files.order_by('path')
    if not project_files.exists() and session.generated_codes.exists():
        for gc in session.generated_codes.all():
            ProjectFile.objects.get_or_create(session=session, path=gc.module_name, defaults={'content': gc.code_content, 'status': 'verified'})
        project_files = session.project_files.order_by('path')

    # Select smartest initial code file to display (avoid defaulting to .gitignore)
    active_initial_file = None
    if project_files.exists():
        main_candidates = ['lib/main.dart', 'main.dart', 'main.py', 'app.py', 'src/App.tsx', 'src/index.tsx', 'index.js', 'src/main.js']
        for cand in main_candidates:
            matched = project_files.filter(path__iexact=cand).first()
            if matched:
                active_initial_file = matched
                break
        if not active_initial_file:
            active_initial_file = project_files.exclude(path__startswith='.').exclude(path__iexact='README.md').first()
        if not active_initial_file:
            active_initial_file = project_files.first()
    
    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    seven_days_ago = today_start - timedelta(days=7)
    
    all_sessions = Session.objects.filter(user=request.user).only('id', 'uuid', 'title', 'started_at', 'status', 'user_id').order_by('-started_at')
    
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
    
    # Auto-cleanup stale background jobs whose worker thread was killed during server restart
    stale_cutoff = timezone.now() - timedelta(minutes=5)
    stale_jobs = session.jobs.filter(status__in=['queued', 'running'], updated_at__lt=stale_cutoff)
    for sj in stale_jobs:
        sj.status = 'failed'
        sj.error_message = 'Job timed out or worker process was terminated.'
        sj.save(update_fields=['status', 'error_message', 'updated_at'])

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

    latest_static_run = session.verification_runs.filter(level='static').order_by('-created_at').first()
    latest_runtime_run = session.verification_runs.filter(level='runtime').order_by('-created_at').first()

    return render(request, 'chat.html', {
        'session': session,
        'chat_messages': messages_list,
        'project_files': project_files,
        'generated_codes': project_files,
        'active_initial_file': active_initial_file,
        'latest_static_run': latest_static_run,
        'latest_runtime_run': latest_runtime_run,
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
                "### Codebase Generation Encountered an Issue\n\n"
                f"{j.error_message or 'The build engine encountered an error while generating project files.'}\n\n"
                "Please try again or request modifications to your requirements."
            )
        elif sess.status == 'needs_attention':
            msg_text = (
                "### Complete Project Codebase Ready (Verification Warnings Remain)\n\n"
                f"{j.result_summary or 'All project files have been planned and generated, but some static verification checks need attention.'}\n\n"
                "You can inspect each file in the workspace file tree on the right, view verification issues in the Checks panel, and download the project ZIP."
            )
        else:
            msg_text = (
                "### Complete Project Codebase Ready\n\n"
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
                    content=f"### Generation Failed\n\nAn unexpected worker error occurred: {str(worker_err)}"
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
            "### Codebase Generation Started\n\n"
            "I have started planning, generating, and verifying your project files in the background.\n\n"
            "You can watch real-time generation and static verification in the progress banner above. The workspace files will populate automatically as they complete."
        )
    else:
        JobExecutionEngine.run_job(job.id, provider_name=provider_name)
        job.refresh_from_db()
        session.refresh_from_db()
        if job.status == 'failed':
            response_text = (
                "### Codebase Generation Encountered an Issue\n\n"
                f"{job.error_message or 'The build engine encountered an error while generating project files.'}\n\n"
                "Please try again or request modifications to your requirements."
            )
        elif session.status == 'needs_attention':
            response_text = (
                "### Complete Project Codebase Ready (Verification Warnings Remain)\n\n"
                f"{job.result_summary or 'All project files have been planned and generated, but some static verification checks need attention.'}\n\n"
                "You can inspect each file in the workspace file tree on the right, view the architecture plan and verification checks, and download your turnkey project ZIP."
            )
        else:
            response_text = (
                "### Complete Project Codebase Ready\n\n"
                f"{job.result_summary or 'All project files have been planned, generated, and verified.'}\n\n"
                "You can inspect each file in the workspace file tree on the right, view the architecture plan and verification checks, and download your turnkey project ZIP."
            )
    return job, response_text


def _handle_module_edit(session, user_content, summary, existing_files, provider_name, user):
    from generator.harmonizer import UniversalProjectHarmonizer
    from generator.repair import CodeRepairEngine
    from generator.verifier import StaticVerifier
    from generator.runtime_verifier import RuntimeVerifier
    from chat.models import VerificationRun, ProjectFile

    files_dict = {f.path: f.content for f in session.project_files.all()}
    
    # 1. Deterministic Harmonization
    UniversalProjectHarmonizer.harmonize(files_dict)
    
    # 2. Check if user is reporting errors, asking to fix, or pasting compiler logs
    error_keywords = ['error', 'errors', 'fix', 'repair', 'broken', 'fail', 'undefined', 'exception', 'stack trace', 'run.sh', 'crash', 'working?', 'verify']
    is_error_fix_request = any(k in user_content.lower() for k in error_keywords) or '•' in user_content or 'error:' in user_content.lower() or 'traceback' in user_content.lower()
    
    plan_obj = session.plans.first()
    plan_data = plan_obj.plan_data if plan_obj and isinstance(plan_obj.plan_data, dict) else None

    # Check which specific files are referenced in the user's message
    mentioned_files = [pf for pf in existing_files if pf.path.lower() in user_content.lower() or os.path.basename(pf.path).lower() in user_content.lower()]

    if is_error_fix_request or len(mentioned_files) > 1:
        logger.info("[CHAT REPAIR] User requested multi-file / compiler error fix. Running comprehensive repair loop...")
        repair_res = CodeRepairEngine.run_repair_loop(
            session=session,
            files_dict=files_dict,
            plan_data=plan_data,
            max_attempts=4,
            provider_name=provider_name
        )
        updated_files = repair_res['files']
        
        # Persist updated files
        modified_paths = []
        for path, new_content in updated_files.items():
            pf = session.project_files.filter(path=path).first()
            if pf:
                if pf.content != new_content:
                    pf.create_new_version(new_content, source='user_feedback')
                    modified_paths.append(path)
            else:
                ProjectFile.objects.create(session=session, path=path, content=new_content, status='verified', current_version=1)
                modified_paths.append(path)

        # Run native runtime compiler verification
        final_verif = RuntimeVerifier.run_verification(updated_files, user=user, plan_data=plan_data)
        if final_verif.get('executed'):
            VerificationRun.objects.create(
                session=session,
                level='runtime',
                passed=final_verif['passed'],
                error_count=final_verif['error_count'],
                warning_count=final_verif['warning_count'],
                issues=final_verif['issues'],
                duration_ms=0
            )

        err_cnt = final_verif.get('error_count', 0)
        warn_cnt = final_verif.get('warning_count', 0)
        
        if err_cnt == 0:
            status_text = "**All compiler and static checks passed with 0 errors.**"
        else:
            status_text = f"Compiler checks report {err_cnt} error(s) remaining."

        file_list_str = "\n".join([f"- `{p}`" for p in modified_paths]) if modified_paths else "All files inspected and harmonized."

        return (
            f"### Codebase Repaired and Verified\n\n"
            f"I have inspected the project and resolved the reported issues across all files:\n\n"
            f"{file_list_str}\n\n"
            f"**Verification Status**: {status_text} ({warn_cnt} warnings)\n\n"
            f"The codebase is fully up to date. You can re-run `./run.sh` or download the updated ZIP anytime."
        )
    else:
        source_pfs = [pf for pf in existing_files if not pf.path.endswith(('.sh', '.bat', '.gitignore', '.gitkeep', '.md', '.yaml', '.yml'))]
        default_pf = source_pfs[-1] if source_pfs else existing_files[-1]
        target_pf = mentioned_files[0] if mentioned_files else default_pf
        updated_code = CodeBuilder.generate_code_for_module(
            target_pf.path,
            summary,
            modifications=user_content,
            provider_name=provider_name,
            session=session,
            user=user
        )
        target_pf.create_new_version(updated_code, source='user_feedback')
        files_dict[target_pf.path] = updated_code
        UniversalProjectHarmonizer.harmonize(files_dict)
        
        # Save any harmonized manifest changes
        for h_path in ('pubspec.yaml', 'requirements.txt', 'package.json'):
            if h_path in files_dict:
                h_pf = session.project_files.filter(path=h_path).first()
                if h_pf and h_pf.content != files_dict[h_path]:
                    h_pf.create_new_version(files_dict[h_path], source='harmonizer')

        verif_res = StaticVerifier.verify_project(files_dict)
        runtime_res = RuntimeVerifier.run_verification(files_dict, user=user, plan_data=plan_data)
        
        err_cnt = runtime_res.get('error_count', verif_res.get('error_count', 0))
        target_pf.status = 'has_issues' if err_cnt > 0 else 'verified'
        target_pf.save(update_fields=['status'])

        verif_msg = f"\n\n**Compiler / Static Verification**: {'0 errors (Passed)' if err_cnt == 0 else f'{err_cnt} error(s) remaining.'}"

        return (
            f"### Updated Module `{target_pf.path}`\n\n"
            f"I have modified `{target_pf.path}` based on your request: *\"{user_content}\"*\n\n"
            f"You can review the updated code in the right panel and download the project ZIP anytime.{verif_msg}"
        )


_CHANGE_VERBS = r'\b(add|remove|delete|change|modify|update|rename|replace|fix|make|use|switch|include|refactor|rewrite|edit|implement)\b'
_QUESTION_START = r'^(what|why|how|where|when|which|who|explain|describe|is|are|does|do|should|could)\b'


def _looks_like_question(text):
    """True for questions about the code ("what does this file do?"),
    False for change requests phrased as questions ("can you add a due date?")."""
    t = (text or '').strip().lower()
    if not t:
        return False
    if re.search(r'\b(error|errors|fix|repair|crash|failing|failed|issue|issues|broken|resolve|traceback)\b', t):
        return False
    if re.search(_CHANGE_VERBS, t) and not re.match(r'^(what|why|how|where|when|which|who|explain|describe)\b', t):
        return False
    return t.endswith('?') or bool(re.match(_QUESTION_START, t))


def _handle_post_generation_qa(session, user_content, summary, provider_name, user, focus_file=None, in_progress=False):
    if in_progress:
        state_line = (
            "The project is being generated module by module and is not finished yet. "
            "Answer the question without changing any code."
        )
    else:
        state_line = "The user's project codebase has already been generated and packaged into a ZIP."
    file_context = ""
    if focus_file is not None:
        file_context = f"Current file `{focus_file.path}`:\n```\n{focus_file.content[:6000]}\n```\n\n"
    post_prompt = (
        f"Project Specification:\n{summary}\n\n"
        f"{file_context}"
        f"User Question: \"{user_content}\"\n\n"
        f"{state_line} "
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
        f"### Incremental Generation Complete\n\n"
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
            r'\b(modify|update|refactor|rewrite|edit|fix|repair|resolve|error|errors|bug|bugs|issue|issues|broken|crash|failing|failed|check|verify|working)\b',
            r'\bchange\s+(the\s+)?(code|module|file|function|class|model|view|schema|implementation)\b'
        ]
        has_error_traces = ('•' in user_content) or ('error:' in user_content.lower()) or ('traceback' in user_content.lower())
        wants_edit = (action == 'edit') or has_error_traces or any(re.search(pat, user_content, re.IGNORECASE) for pat in edit_patterns)
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


def _handle_mode3_message(session, user_content, action, provider_name, history, user):
    """
    Mode 3: Quick Code / Code Snippet / Fixer Mode.
    Provides direct code generation, bug fixing, script writing, refactoring, or programming answers
    without multi-turn requirement elicitation or multi-file project scaffolding.
    """
    dialogue_context = ""
    if history:
        turns = []
        for m in history[-6:]:
            role = "User" if m.get('role') == 'user' else "Assistant"
            turns.append(f"{role}: {m.get('content', '')}")
        dialogue_context = "Recent Conversation History:\n" + "\n\n".join(turns) + "\n\n"

    system_prompt = (
        "You are DevDialogue AI in Quick Code / Direct Code Mode — an elite AI software engineer. "
        "Your task is to provide direct, clean, robust code snippets, solutions, and bug fixes immediately "
        "without unnecessary delay or multi-turn interview questions.\n"
        "- When the user asks for code, a function, script, snippet, algorithm, or small program: write complete, production-ready code with concise explanations.\n"
        "- When the user provides broken or buggy code, compiler errors, or tracebacks: diagnose the root cause, explain the fix concisely, and provide the fully corrected, working code.\n"
        "- When the user asks a technical programming question: give a direct, accurate answer with practical code examples.\n"
        "- Always format code inside markdown code blocks with the appropriate language identifier (e.g. ```python, ```dart, ```javascript).\n"
        "- Strictly do not use any emojis in your response."
    )

    prompt = (
        f"{dialogue_context}"
        f"User Request:\n{user_content}\n\n"
        "Provide the complete code solution, fix, or explanation directly:"
    )

    response_text = LLMRouter.generate(
        prompt=prompt,
        system_prompt=system_prompt,
        provider_name=provider_name,
        purpose='chat',
        session=session,
        user=user
    )

    if session.status != 'ready':
        session.status = 'ready'
        session.save(update_fields=['status'])

    return None, response_text


def _run_mode2_worker(job_id, provider_name, task, save_message=True):
    """Background worker for File-by-file mode. task is 'next_module' or 'complete'."""
    from django.db import connection
    from django.utils import timezone
    from chat.models import Job
    job = None
    try:
        job = Job.objects.select_related('session', 'user').get(id=job_id)
        job.status = 'running'
        job.updated_at = timezone.now()
        job.save(update_fields=['status', 'updated_at'])
        session = job.session
        if task == 'complete':
            job.log_event('info', 'Verifying and repairing the completed project...')
            plan_obj = session.plans.first()
            msg_text = _complete_incremental_project(session, plan_obj, provider_name)
        else:
            job.log_event('info', 'Generating the next module...')
            _, _, _, msg_text = _generate_next_module(session=session, user=job.user, provider_name=provider_name, summary=session.summary_text or None)
        if save_message:
            Message.objects.create(session=session, role='assistant', content=msg_text)
        job.result_summary = msg_text
        job.status = 'succeeded'
        job.progress_current = job.progress_total
        job.updated_at = timezone.now()
        job.save(update_fields=['result_summary', 'status', 'progress_current', 'updated_at'])
    except Exception as worker_err:
        if job is not None:
            job.status = 'failed'
            job.error_message = str(worker_err)
            job.updated_at = timezone.now()
            job.save(update_fields=['status', 'error_message', 'updated_at'])
            Message.objects.create(
                session=job.session, role='assistant',
                content=f"### Module Generation Failed\n\n{worker_err}\n\nSay **yes** to try again."
            )
    finally:
        connection.close()


def _start_mode2_task(session, user, provider_name, task, run_async=True):
    """Runs a File-by-file step as a background Job (async) or inline (tests).
    Returns (job_or_None, response_text)."""
    from generator.jobs import JobExecutionEngine
    job = JobExecutionEngine.create_job(session=session, user=user, job_type='module')
    if run_async:
        import threading
        threading.Thread(target=_run_mode2_worker, args=(job.id, provider_name, task), daemon=True).start()
        if task == 'complete':
            return job, "### Verifying your project...\n\nAll modules are approved. Running final verification and repair in the background."
        return job, "### Generating the next module...\n\nThis runs in the background; the file will appear on the right when it's ready."
    # Inline (tests / X-Run-Sync: true): the caller saves the reply as the assistant message
    _run_mode2_worker(job.id, provider_name, task, save_message=False)
    job.refresh_from_db()
    session.refresh_from_db()
    if job.status == 'failed':
        raise RuntimeError(job.error_message or 'Module generation failed')
    return None, job.result_summary


def _handle_mode2_message(session, user_content, action, is_approval, provider_name, history, user, run_async=True):
    """File-by-file routing. Returns (active_job, response_text).

    Decision order for every step:
      1. Question about the code     -> answer, never touch files
      2. Approval (button or 'yes')  -> next module, or final verification after the last one
      3. Anything else               -> change request for the current module
    """
    summary = session.summary_text or SRSSynthesizer.synthesize_summary(history, is_mode2=True, provider_name=provider_name, session=session, user=user)
    plan_obj = session.plans.first()
    modules = plan_obj.generation_order if plan_obj else FilePlanner.get_module_list(summary)
    existing_files = list(session.project_files.filter(path__in=modules)) if modules else []
    current_file = max(existing_files, key=lambda f: f.updated_at) if existing_files else None
    is_question = action is None and not is_approval and _looks_like_question(user_content)

    # A. Project already finished: questions -> Q&A, everything else -> edit
    if session.status in ('completed', 'ready', 'needs_attention'):
        if is_question or not existing_files:
            return None, _handle_post_generation_qa(session, user_content, summary, provider_name, user)
        return None, _handle_module_edit(session, user_content, summary, existing_files, provider_name, user)

    # B. No module generated yet (reviewing the requirements summary)
    if not existing_files:
        if is_approval:
            return _start_mode2_task(session, user, provider_name, 'next_module', run_async)
        if is_question:
            return None, _handle_post_generation_qa(session, user_content, summary, provider_name, user, in_progress=True)
        # Requirement change: rebuild the summary from the full history (which includes this message)
        new_summary = SRSSynthesizer.synthesize_summary(history, is_mode2=True, provider_name=provider_name, session=session, user=user)
        session.summary_text = new_summary
        session.save(update_fields=['summary_text'])
        session.plans.all().delete()  # plan was built from the old summary
        return None, new_summary

    # C. Reviewing a module
    if is_question:
        return None, _handle_post_generation_qa(session, user_content, summary, provider_name, user, focus_file=current_file, in_progress=True)
    if is_approval:
        task = 'complete' if len(existing_files) >= len(modules) else 'next_module'
        return _start_mode2_task(session, user, provider_name, task, run_async)
    # Change request: edit the file the user names, else the module under review
    if current_file is not None:
        existing_files = [f for f in existing_files if f.pk != current_file.pk] + [current_file]
    return None, _handle_module_edit(session, user_content, summary, existing_files, provider_name, user)



@verification_required
def send_message_api(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)
        
    session = _get_session(session_id, request.user, select_related=['user'])
    active_job = None
    if request.headers.get('X-Run-Sync') == 'false':
        run_async = True
    elif request.headers.get('X-Run-Sync') == 'true' or request.GET.get('sync') == '1':
        run_async = False
    else:
        run_async = not getattr(settings, 'IS_TESTING', False)
        
    file_bytes = None
    file_name = None
    content_type = ''

    # Handle multipart file upload if present
    uploaded_file = request.FILES.get('file') or request.FILES.get('attachment')
    if uploaded_file:
        file_bytes = uploaded_file.read()
        file_name = uploaded_file.name
        content_type = getattr(uploaded_file, 'content_type', '')

    user_content = ''
    provider_name = None
    action = None
    req_id = None
    edit_message_id = None

    try:
        data = json.loads(request.body)
        user_content = data.get('message', '').strip()
        provider_name = data.get('provider', None)
        action = data.get('action', None)
        req_id = data.get('request_id', None)
        edit_message_id = data.get('edit_message_id', None)
        if not file_bytes and data.get('file_base64'):
            import base64
            try:
                file_bytes = base64.b64decode(data['file_base64'])
                file_name = data.get('file_name', 'attachment.bin')
                content_type = data.get('content_type', '')
            except Exception:
                pass
    except Exception:
        user_content = request.POST.get('message', '').strip()
        provider_name = request.POST.get('provider', None)
        action = request.POST.get('action', None)
        req_id = request.POST.get('request_id', None)
        edit_message_id = request.POST.get('edit_message_id', None)

    if not user_content and file_name:
        user_content = f"Please analyze the attached {file_name} and incorporate its requirements and architecture specifications."
        
    if not user_content and not file_bytes:
        return JsonResponse({'error': 'Message content or attachment is required'}, status=400)
        
    from django.core.cache import cache
    # Clear any old session cancellation flag so future messages are never swallowed (#2)
    cache.delete(f"cancel_session_{session.id}")

    attachment_obj = None
    if file_bytes and file_name:
        from chat.models import MessageAttachment
        from chat.document_processor import DocumentProcessor
        from django.core.files.base import ContentFile

        extracted_text, f_type, meta = DocumentProcessor.extract_content(
            file_bytes=file_bytes,
            filename=file_name,
            content_type=content_type,
            user=request.user
        )

        attachment_obj = MessageAttachment.objects.create(
            session=session,
            file_name=file_name,
            file_type=f_type,
            file_size=len(file_bytes),
            extracted_text=extracted_text,
            metadata=meta
        )
        attachment_obj.file.save(file_name, ContentFile(file_bytes), save=True)

    if edit_message_id:
        try:
            edit_id = int(edit_message_id)
            user_msg = session.messages.filter(id=edit_id, role='user').first()
        except (ValueError, TypeError):
            user_msg = None

        if user_msg:
            session.messages.filter(id__gt=user_msg.id).delete()
            user_msg.content = user_content
            user_msg.save(update_fields=['content'])
        else:
            user_msg = Message.objects.create(session=session, role='user', content=user_content)
    else:
        user_msg = Message.objects.create(session=session, role='user', content=user_content)
    if attachment_obj:
        attachment_obj.message = user_msg
        attachment_obj.save(update_fields=['message'])

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

        if session.mode == 'mode3':
            active_job, response_text = _handle_mode3_message(session, user_content, action, provider_name, history, request.user)
            extracted = extract_code_files_from_markdown(response_text)
            for fn, code_c in extracted:
                pf, _ = ProjectFile.objects.get_or_create(session=session, path=fn, defaults={'content': code_c, 'status': 'verified'})
                if pf.content != code_c:
                    pf.create_new_version(code_c, source='generator')
        else:
            has_summary = any(
                re.search(r'#+\s*(?:Project\s+)?Requirements\s+Summary', m['content'], re.IGNORECASE)
                for m in assist_msgs
            ) or bool(session.summary_text) or session.status in ('srs_ready', 'plan_draft', 'plan_approved', 'generating', 'ready', 'needs_attention', 'completed')
            
            if has_summary:
                is_approval = False
                if action in ('generate', 'approve_module'):
                    is_approval = True
                elif action == 'changes':
                    is_approval = False
                else:
                    confirmation_msg = user_content.lower().strip()
                    has_negation = bool(re.search(r'\b(no|not|don\'?t|never|wait|stop|hold|cancel|refuse)\b', confirmation_msg))
                    if action is None and not has_negation:
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
                        # "yes, proceed with the first module" / "ok continue": affirmative opener and no
                        # change request inside ("yes, but add an admin panel" stays a change request)
                        elif re.match(r'^(yes|yep|yup|yeah|sure|ok|okay|approved?|proceed|go ahead|continue|next|looks good|lgtm)\b', confirmation_msg) \
                                and not re.search(_CHANGE_VERBS, confirmation_msg):
                            is_approval = True

                if session.mode == 'mode1':
                    active_job, response_text = _handle_mode1_message(session, user_content, action, is_approval, provider_name, run_async, history, request.user)
                else:
                    active_job, response_text = _handle_mode2_message(session, user_content, action, is_approval, provider_name, history, request.user, run_async=run_async)
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
                        # Build summary + plan now (fast enough), generate Module 1 in the background
                        if not session.summary_text:
                            session.summary_text = SRSSynthesizer.synthesize_summary(history, is_mode2=True, provider_name=provider_name, session=session, user=request.user)
                            session.save(update_fields=['summary_text'])
                            SessionStateMachine.transition_to(session, 'srs_ready')
                        active_job, response_text = _start_mode2_task(session, request.user, provider_name, 'next_module', run_async=run_async)
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
        err_msg = "The AI service is temporarily unavailable or experiencing high traffic. Please try sending your message again in a few moments."
        Message.objects.create(session=session, role='assistant', content=err_msg)
        return JsonResponse({
            'error': str(rerr),
            'response': err_msg,
            'status': session.status
        }, status=503)
    except Exception as gen_err:
        import logging
        logging.getLogger(__name__).exception("Unhandled exception in send_message_api")
        err_msg = "An unexpected server error occurred while processing your message. Please try again."
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
            'response': 'Message generation was cancelled by user.',
            'status': session.status
        })

    assistant_msg = Message.objects.create(session=session, role='assistant', content=response_text)

    
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
        'job_id': active_job.id if active_job else None,
        'user_message_id': user_msg.id,
        'assistant_message_id': assistant_msg.id,
        'attachment': {
            'id': attachment_obj.id,
            'file_name': attachment_obj.file_name,
            'file_type': attachment_obj.file_type,
            'file_size': attachment_obj.file_size,
            'file_url': attachment_obj.file.url if attachment_obj.file else None
        } if attachment_obj else None
    })

@verification_required
def stream_chat_api(request, session_id):
    """
    Real-time Server-Sent Events (SSE) streaming endpoint for DevDialogue AI.
    Emits structured agent activity feed events (thinking, tool_call, tool_result,
    source, file_action, answer_chunk, error, done) directly as each step occurs.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)

    session = _get_session(session_id, request.user, select_related=['user'])

    file_bytes = None
    file_name = None
    content_type = ''

    # Handle multipart file upload if present
    uploaded_file = request.FILES.get('file') or request.FILES.get('attachment')
    if uploaded_file:
        file_bytes = uploaded_file.read()
        file_name = uploaded_file.name
        content_type = getattr(uploaded_file, 'content_type', '')

    user_content = ''
    provider_name = None
    action = None
    req_id = None
    edit_message_id = None

    try:
        data = json.loads(request.body)
        user_content = data.get('message', '').strip()
        provider_name = data.get('provider', None)
        action = data.get('action', None)
        req_id = data.get('request_id', None)
        edit_message_id = data.get('edit_message_id', None)
        if not file_bytes and data.get('file_base64'):
            import base64
            try:
                file_bytes = base64.b64decode(data['file_base64'])
                file_name = data.get('file_name', 'attachment.bin')
                content_type = data.get('content_type', '')
            except Exception:
                pass
    except Exception:
        user_content = request.POST.get('message', '').strip()
        provider_name = request.POST.get('provider', None)
        action = request.POST.get('action', None)
        req_id = request.POST.get('request_id', None)
        edit_message_id = request.POST.get('edit_message_id', None)

    if not user_content and file_name:
        user_content = f"Please analyze the attached {file_name} and incorporate its requirements and architecture specifications."

    if not user_content and not file_bytes:
        return JsonResponse({'error': 'Message content or attachment is required'}, status=400)

    logger.info("[STREAM API HIT] Session #%s | Action: %s | Provider: %s | RequestID: %s | User: %s", session.id, action, provider_name, req_id, request.user)
    if user_content:
        logger.info("[USER PROMPT] \"%s\"", user_content[:150] + ('...' if len(user_content) > 150 else ''))

    # Process attachment if uploaded
    attachment_obj = None
    if file_bytes and file_name:
        from chat.models import MessageAttachment
        from chat.document_processor import DocumentProcessor
        from django.core.files.base import ContentFile

        logger.info("[ATTACHMENT] Extracting text & structure from '%s' (%s bytes, %s)...", file_name, len(file_bytes), content_type)
        extracted_text, f_type, meta = DocumentProcessor.extract_content(
            file_bytes=file_bytes,
            filename=file_name,
            content_type=content_type,
            user=request.user
        )
        logger.info("[ATTACHMENT PARSED] '%s' (%s): %d chars of text extracted (metadata: %s)", file_name, f_type, len(extracted_text), meta)

        attachment_obj = MessageAttachment.objects.create(
            session=session,
            file_name=file_name,
            file_type=f_type,
            file_size=len(file_bytes),
            extracted_text=extracted_text,
            metadata=meta
        )
        attachment_obj.file.save(file_name, ContentFile(file_bytes), save=True)

    from chat.events import stream_agent_response

    run_sync = request.headers.get('X-Run-Sync') == 'true'

    response = StreamingHttpResponse(
        stream_agent_response(
            session=session,
            user_content=user_content,
            provider_name=provider_name,
            action=action,
            user=request.user,
            request_id=req_id,
            attachment=attachment_obj,
            edit_message_id=edit_message_id,
            run_sync=run_sync
        ),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache, no-transform'
    response['X-Accel-Buffering'] = 'no'
    return response

@verification_required
def delete_session_view(request, session_id):
    if request.method == 'POST':
        session = _get_session(session_id, request.user)
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
            
        session = _get_session(session_id, request.user)
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
    from chat.models import Job, JobEvent
    job = get_object_or_404(Job, id=job_id, user=request.user)

    # Auto-fail stalled / orphaned background jobs whose worker thread was killed
    if job.status in ['queued', 'running'] and (timezone.now() - job.updated_at) > timedelta(minutes=5):
        job.status = 'failed'
        job.error_message = 'Job timed out or worker process was terminated.'
        job.save(update_fields=['status', 'error_message', 'updated_at'])
        last_seq = job.events.count()
        JobEvent.objects.create(
            job=job,
            sequence_number=last_seq + 1,
            kind='error',
            message='Job timed out or worker process was terminated.'
        )
    
    try:
        after_seq = int(request.GET.get('after', 0))
    except (ValueError, TypeError):
        after_seq = 0

    events = list(job.events.filter(sequence_number__gt=after_seq).values(
        'sequence_number', 'kind', 'message', 'data', 'created_at'
    ))
    
    return JsonResponse({
        'job_id': job.id,
        'job_type': job.job_type,
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
    session = _get_session(session_id, request.user)
    
    # Specific per-request cancellation (#2)
    request_id = None
    try:
        if request.body:
            data = json.loads(request.body)
            request_id = data.get('request_id')
    except Exception:
        pass
    if not request_id:
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
    session = _get_session(session_id, request.user)
    if request.method == 'POST':
        # Lock mode switching if generation has started or files exist
        if session.status not in ('active', 'interviewing', 'ready') or session.project_files.exists() or session.jobs.filter(status__in=['running', 'queued', 'succeeded']).exists():
            return JsonResponse({'error': 'Mode cannot be changed once generation has started or files exist.'}, status=400)
        try:
            data = json.loads(request.body)
            new_mode = data.get('mode')
        except Exception:
            new_mode = request.POST.get('mode')
        if new_mode in ('mode1', 'mode2', 'mode3'):
            session.mode = new_mode
        else:
            cycle = {'mode1': 'mode2', 'mode2': 'mode3', 'mode3': 'mode1'}
            session.mode = cycle.get(session.mode, 'mode1')
        session.save(update_fields=['mode'])
        return JsonResponse({'status': 'success', 'mode': session.mode})
    return JsonResponse({'error': 'POST required'}, status=400)

@verification_required
def approve_plan_api(request, session_id):
    from chat.models import ProjectPlan
    from chat.state_machine import SessionStateMachine
    if request.method == 'POST':
        session = _get_session(session_id, request.user)
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
    session = _get_session(session_id, request.user)
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
def run_verification_api(request, session_id):
    """
    On-demand execution of project verification (Static AST/Syntax + Runtime compiler checks).
    Invoked when user clicks the Verification buttons in the workspace header.
    """
    from generator.verifier import StaticVerifier
    from generator.runtime_verifier import RuntimeVerifier
    from generator.harmonizer import UniversalProjectHarmonizer
    from chat.models import VerificationRun

    session = _get_session(session_id, request.user)
    files_dict = {f.path: f.content for f in session.project_files.all()}
    if not files_dict:
        return JsonResponse({
            'status': 'no_files',
            'has_files': False,
            'message': 'No project files generated yet in this workspace.'
        })

    plan_obj = session.plans.first()
    plan_data = plan_obj.plan_data if plan_obj and isinstance(plan_obj.plan_data, dict) else None

    # Harmonize dependencies and manifests across files
    UniversalProjectHarmonizer.harmonize(files_dict)
    for h_path in ('pubspec.yaml', 'requirements.txt', 'package.json'):
        if h_path in files_dict:
            h_pf = session.project_files.filter(path=h_path).first()
            if h_pf and h_pf.content != files_dict[h_path]:
                h_pf.create_new_version(files_dict[h_path], source='harmonizer')

    static_res = StaticVerifier.verify_project(files_dict, plan_data=plan_data)
    runtime_res = RuntimeVerifier.run_verification(files_dict, user=request.user, plan_data=plan_data)

    static_errors = static_res.get('error_count', 0)
    static_run = VerificationRun.objects.create(
        session=session,
        level='static',
        passed=static_errors == 0,
        error_count=static_errors,
        warning_count=static_res.get('warning_count', 0),
        issues=static_res.get('issues', [])
    )

    runtime_run = None
    if runtime_res.get('executed'):
        r_errors = runtime_res.get('error_count', 0)
        runtime_run = VerificationRun.objects.create(
            session=session,
            level='runtime',
            passed=r_errors == 0,
            error_count=r_errors,
            warning_count=runtime_res.get('warning_count', 0),
            issues=runtime_res.get('issues', [])
        )

    # Update individual file statuses
    issue_files = set(i.get('file') for i in static_res.get('issues', []) if i.get('severity') == 'error')
    if runtime_res.get('executed'):
        issue_files.update(i.get('file') for i in runtime_res.get('issues', []) if i.get('severity') == 'error')

    for pf in session.project_files.all():
        st = 'has_issues' if pf.path in issue_files else 'verified'
        if pf.status != st:
            pf.status = st
            pf.save(update_fields=['status'])

    total_errors = static_errors + (runtime_run.error_count if runtime_run else 0)
    if total_errors == 0:
        if session.status == 'needs_attention':
            session.status = 'ready'
            session.save(update_fields=['status'])
    else:
        if session.status == 'ready':
            session.status = 'needs_attention'
            session.save(update_fields=['status'])

    logger.info("[VERIFICATION RUN] Session #%s (%s) verified: static errors=%d, runtime errors=%d (passed=%s)",
                session.id, session.uuid, static_errors, runtime_run.error_count if runtime_run else 0, total_errors == 0)

    return JsonResponse({
        'status': 'ok',
        'has_files': True,
        'static': {
            'passed': static_run.passed,
            'error_count': static_run.error_count,
            'warning_count': static_run.warning_count,
            'issues': static_run.issues,
            'total_files': len(files_dict)
        },
        'runtime': {
            'executed': runtime_res.get('executed', False),
            'passed': runtime_run.passed if runtime_run else True,
            'error_count': runtime_run.error_count if runtime_run else 0,
            'warning_count': runtime_run.warning_count if runtime_run else 0,
            'issues': runtime_run.issues if runtime_run else [],
        },
        'total_errors': total_errors
    })


@verification_required
def get_verification_api(request, session_id):
    if request.method == 'POST':
        return run_verification_api(request, session_id)
    from chat.models import VerificationRun
    session = _get_session(session_id, request.user)
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
def get_session_diffs_api(request, session_id):
    import difflib
    session = _get_session(session_id, request.user)
    files = session.project_files.prefetch_related('versions').all().order_by('path')

    file_diffs = []
    for pf in files:
        versions = list(pf.versions.all().order_by('version_number'))
        v_count = len(versions)
        diff_lines = []
        if v_count >= 2:
            prev_ver = versions[-2]
            curr_ver = versions[-1]
            old_lines = prev_ver.content.splitlines()
            new_lines = curr_ver.content.splitlines()
            matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == 'equal':
                    for k in range(j1, j2):
                        diff_lines.append({
                            'type': 'unchanged',
                            'old_num': i1 + (k - j1) + 1,
                            'new_num': k + 1,
                            'text': new_lines[k]
                        })
                elif tag == 'replace':
                    for k in range(i1, i2):
                        diff_lines.append({
                            'type': 'removed',
                            'old_num': k + 1,
                            'new_num': '',
                            'text': old_lines[k]
                        })
                    for k in range(j1, j2):
                        diff_lines.append({
                            'type': 'added',
                            'old_num': '',
                            'new_num': k + 1,
                            'text': new_lines[k]
                        })
                elif tag == 'delete':
                    for k in range(i1, i2):
                        diff_lines.append({
                            'type': 'removed',
                            'old_num': k + 1,
                            'new_num': '',
                            'text': old_lines[k]
                        })
                elif tag == 'insert':
                    for k in range(j1, j2):
                        diff_lines.append({
                            'type': 'added',
                            'old_num': '',
                            'new_num': k + 1,
                            'text': new_lines[k]
                        })
        elif v_count == 1:
            curr_ver = versions[0]
            new_lines = curr_ver.content.splitlines()
            for k, line in enumerate(new_lines[:150]):
                diff_lines.append({
                    'type': 'added',
                    'old_num': '',
                    'new_num': k + 1,
                    'text': line
                })

        file_diffs.append({
            'file_id': pf.id,
            'path': pf.path,
            'current_version': pf.current_version,
            'version_count': v_count,
            'versions': [
                {
                    'version_number': v.version_number,
                    'source': v.get_source_display(),
                    'created_at': v.created_at.strftime('%H:%M:%S')
                }
                for v in versions
            ],
            'diff_lines': diff_lines
        })

    return JsonResponse({
        'session_id': session.id,
        'has_diffs': any(f['version_count'] >= 2 for f in file_diffs) or len(file_diffs) > 0,
        'files': file_diffs
    })

@verification_required
def get_file_tree_api(request, session_id):
    from chat.models import ProjectFile
    session = _get_session(session_id, request.user)
    p_files = list(session.project_files.order_by('path').values('id', 'path', 'status', 'current_version', 'updated_at'))
    
    return JsonResponse({
        'project_files': p_files,
        'generated_codes': [{'id': f['id'], 'module_name': f['path']} for f in p_files]
    })

@verification_required
def delete_message_api(request, session_id, message_id):
    """
    Unsend / delete a chat message.
    Also deletes any assistant response that directly answered this message,
    and updates session status and completeness score.
    """
    if request.method not in ('POST', 'DELETE'):
        return JsonResponse({'error': 'POST or DELETE request required'}, status=405)

    session = _get_session(session_id, request.user, select_related=['user'])
    target_msg = session.messages.filter(id=message_id).first()
    if not target_msg:
        return JsonResponse({'error': 'Message not found'}, status=404)

    # Find associated assistant replies following this user message before any next user message
    next_user_msg = session.messages.filter(id__gt=target_msg.id, role='user').order_by('id').first()
    if next_user_msg:
        associated_replies = list(session.messages.filter(id__gt=target_msg.id, id__lt=next_user_msg.id, role='assistant'))
    else:
        associated_replies = list(session.messages.filter(id__gt=target_msg.id, role='assistant'))

    deleted_reply_ids = [r.id for r in associated_replies]

    # Delete replies and target message
    for r in associated_replies:
        r.delete()
    target_msg.delete()

    # Recalculate remaining history and session state
    remaining_messages = list(session.messages.values('role', 'content'))
    if not remaining_messages:
        session.status = 'active'
        session.save(update_fields=['status'])
        comp_score = 0
    else:
        try:
            comp_score = CompletenessEngine.compute_completeness_score(remaining_messages)
        except Exception:
            comp_score = 0

    logger.info("[DELETE MESSAGE] Session #%s | Deleted Message #%s (%s) | Cascade deleted %d assistant replies (%s) | Remaining messages: %d",
        session.id, message_id, target_msg.role, len(deleted_reply_ids), deleted_reply_ids, len(remaining_messages))

    return JsonResponse({
        'success': True,
        'deleted_message_id': message_id,
        'deleted_reply_ids': deleted_reply_ids,
        'remaining_count': len(remaining_messages),
        'completeness_score': comp_score,
        'session_status': session.status
    })



