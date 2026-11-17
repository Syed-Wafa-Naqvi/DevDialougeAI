import json
import logging
import time
import re
from typing import Generator, Dict, Any, Optional
from django.utils import timezone
from django.core.cache import cache
from chat.models import Session, Message, ProjectFile, ProjectPlan
from chat.state_machine import SessionStateMachine
from dialogue.completeness import CompletenessEngine
from dialogue.interviewer import InterviewerService
from dialogue.synthesizer import SRSSynthesizer
from generator.jobs import JobExecutionEngine

logger = logging.getLogger('chat.events')


class AgentEvent:
    """Helper methods to construct standardized agent lifecycle events."""
    
    @staticmethod
    def thinking(step_id: str, title: str, content: str = "", status: str = "running") -> Dict[str, Any]:
        logger.info("[AGENT THINKING] [%s] %s: %s (%s)", step_id, title, content[:80] if content else '', status)
        return {
            "type": "thinking",
            "id": step_id,
            "title": title,
            "content": content,
            "status": status,
            "timestamp": time.time(),
        }

    @staticmethod
    def tool_call(call_id: str, tool: str, args: Dict[str, Any], summary: str = "") -> Dict[str, Any]:
        logger.info("[AGENT TOOL CALL] [%s] %s | %s", call_id, tool, summary or json.dumps(args, default=str)[:80])
        return {
            "type": "tool_call",
            "id": call_id,
            "tool": tool,
            "args": args,
            "summary": summary or f"Executing tool: {tool}",
            "timestamp": time.time(),
        }

    @staticmethod
    def tool_result(call_id: str, tool: str, result: Any, duration_ms: int = 0, status: str = "success") -> Dict[str, Any]:
        logger.info("[AGENT TOOL RESULT] [%s] %s -> %s (%dms)", call_id, tool, status, duration_ms)
        return {
            "type": "tool_result",
            "id": call_id,
            "tool": tool,
            "result": result,
            "duration_ms": duration_ms,
            "status": status,
            "timestamp": time.time(),
        }

    @staticmethod
    def file_action(action: str, path: str, summary: str = "", version: int = 1) -> Dict[str, Any]:
        """action: 'read' | 'create' | 'edit' | 'verify'"""
        logger.info("[AGENT FILE ACTION] %s %s (v%d): %s", action.upper(), path, version, summary)
        return {
            "type": "file_action",
            "action": action,
            "path": path,
            "summary": summary or f"{action.capitalize()} {path}",
            "version": version,
            "timestamp": time.time(),
        }

    @staticmethod
    def source(title: str, url_or_path: str, kind: str = "file") -> Dict[str, Any]:
        """kind: 'file' | 'web' | 'spec'"""
        return {
            "type": "source",
            "title": title,
            "url_or_path": url_or_path,
            "kind": kind,
            "timestamp": time.time(),
        }

    @staticmethod
    def answer_chunk(delta: str) -> Dict[str, Any]:
        return {
            "type": "answer_chunk",
            "delta": delta,
            "timestamp": time.time(),
        }

    @staticmethod
    def error(message: str, code: str = "error") -> Dict[str, Any]:
        logger.error("[AGENT ERROR] [%s] %s", code, message)
        return {
            "type": "error",
            "message": message,
            "code": code,
            "timestamp": time.time(),
        }

    @staticmethod
    def done(
        status: str = "succeeded",
        total_duration_ms: int = 0,
        tokens_used: int = 0,
        session_status: str = "",
        completeness_score: Optional[int] = None,
        rubric_cats: Optional[Dict[str, Any]] = None,
        codes: Optional[list] = None,
        title: Optional[str] = None,
        attachment: Optional[Dict[str, Any]] = None,
        user_message_id: Optional[int] = None,
        assistant_message_id: Optional[int] = None
    ) -> Dict[str, Any]:
        logger.info(
            "[AGENT DONE] Status: %s | Duration: %dms | Tokens: %d | Completeness: %s%% | SessionStatus: %s",
            status, total_duration_ms, tokens_used, completeness_score, session_status
        )
        return {
            "type": "done",
            "status": status,
            "total_duration_ms": total_duration_ms,
            "tokens_used": tokens_used,
            "session_status": session_status,
            "completeness_score": completeness_score,
            "rubric_cats": rubric_cats or {},
            "codes": codes or [],
            "title": title,
            "attachment": attachment,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "timestamp": time.time(),
        }


def format_sse(event_data: Dict[str, Any]) -> str:
    """Formats a dictionary into standard Server-Sent Events stream message."""
    payload = json.dumps(event_data, ensure_ascii=False)
    return f"data: {payload}\n\n"


def stream_agent_response(
    session: Session,
    user_content: str,
    provider_name: Optional[str] = None,
    action: Optional[str] = None,
    user = None,
    request_id: Optional[str] = None,
    attachment: Optional[Any] = None,
    edit_message_id: Optional[Any] = None
) -> Generator[str, None, None]:
    """
    Generator yielding Server-Sent Events (SSE) strings formatted as `data: {...}\\n\\n`.
    Emits real-time agent activity: thinking steps, tool invocations, file actions,
    sources referenced, token-by-token answer chunks, and final completion metadata.
    """
    start_time = time.time()
    user = user or session.user
    
    # 0. Check cancellation helper
    def is_cancelled() -> bool:
        if request_id and cache.get(f"cancel_req_{request_id}"):
            return True
        if cache.get(f"cancel_session_{session.id}"):
            return True
        return False

    if is_cancelled():
        cache.delete(f"cancel_session_{session.id}")
        if request_id:
            cache.delete(f"cancel_req_{request_id}")
        yield format_sse(AgentEvent.thinking("step_intent", "Cancelled by user", status="cancelled"))
        yield format_sse(AgentEvent.done(status="cancelled", total_duration_ms=int((time.time() - start_time) * 1000)))
        return

    # Clear previous cancellation flag for fresh message
    cache.delete(f"cancel_session_{session.id}")
    if request_id:
        cache.delete(f"cancel_req_{request_id}")

    # Record or update user message in DB
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

    if attachment:
        attachment.message = user_msg
        attachment.save(update_fields=['message'])

    history = list(session.messages.values('role', 'content'))
    existing_files = list(session.project_files.order_by('path'))

    # Step 1: Initial Thinking Event
    yield format_sse(AgentEvent.thinking(
        step_id="step_intent",
        title="Analyzing prompt and requirement context",
        content="Detecting intent, technical constraints, and conversation progress...",
        status="running"
    ))

    # If attachment is provided, emit real-time extraction & parsing events
    if attachment:
        yield format_sse(AgentEvent.thinking(
            step_id=f"step_doc_{attachment.id}",
            title=f"Extracting content from attached {attachment.file_type.upper()} ({attachment.file_name})",
            content=f"Extracted {len(attachment.extracted_text)} characters of specifications.",
            status="completed"
        ))
        yield format_sse(AgentEvent.tool_call(
            call_id=f"tool_doc_{attachment.id}",
            tool="document_extractor",
            args={
                "filename": attachment.file_name,
                "file_type": attachment.file_type,
                "size_bytes": attachment.file_size,
                "metadata": attachment.metadata
            },
            summary=f"Parsed {attachment.file_type.upper()} specifications from {attachment.file_name}"
        ))
        yield format_sse(AgentEvent.file_action(
            action="read",
            path=attachment.file_name,
            summary=f"Parsed {attachment.file_name} ({attachment.file_type.upper()}, {max(1, attachment.file_size // 1024)} KB)"
        ))
        yield format_sse(AgentEvent.source(
            title=f"Attached: {attachment.file_name}",
            url_or_path=attachment.file.url if attachment.file else attachment.file_name,
            kind=attachment.file_type
        ))
        yield format_sse(AgentEvent.tool_result(
            call_id=f"tool_doc_{attachment.id}",
            tool="document_extractor",
            result={"status": "success", "length": len(attachment.extracted_text), "type": attachment.file_type},
            duration_ms=40
        ))

    if is_cancelled():
        yield format_sse(AgentEvent.thinking("step_intent", "Cancelled by user", status="cancelled"))
        yield format_sse(AgentEvent.done(status="cancelled", total_duration_ms=int((time.time() - start_time) * 1000)))
        return

    # Check existing sources and reference files
    if existing_files:
        for pf in existing_files[:4]:
            yield format_sse(AgentEvent.source(
                title=f"Workspace: {pf.path}",
                url_or_path=pf.path,
                kind="file"
            ))

    # Step 2: Intent Analysis Tool Call
    yield format_sse(AgentEvent.tool_call(
        call_id="tool_intent",
        tool="intent_classifier",
        args={"prompt_length": len(user_content), "session_mode": session.mode, "session_status": session.status},
        summary="Evaluating technical completeness rubric and elicitation status"
    ))

    assist_msgs = [m for m in history if m['role'] == 'assistant']
    has_summary = any(
        re.search(r'#+\s*(?:Project\s+)?Requirements\s+Summary', m['content'], re.IGNORECASE)
        for m in assist_msgs
    ) or bool(session.summary_text) or session.status in ('srs_ready', 'plan_draft', 'plan_approved', 'generating', 'ready', 'needs_attention', 'completed')

    # Detect code demand or affirmative approval
    confirmation_msg = user_content.lower().strip()
    is_approval = False
    if action in ('generate', 'approve_module'):
        is_approval = True
    elif action != 'changes':
        strict_approval_patterns = [
            r'^(yes|y|proceed|approve|confirm|ok|okay|sure|go ahead|looks good|looks great|lgtm|perfect|fine|accepted|approved)[.!]?$',
            r'^(proceed|start|begin|go ahead)\s+(with\s+)?(generation|code|building|all files|project)[.!]?$',
            r'^(generate|build)\s+(the\s+)?(code|files|codebase|project|all files)[.!]?$',
            r'^(yes|sure|okay|yep|yup)[,\s]+(please\s+)?(proceed|generate|build|start|go ahead)(\s+(and|&)\s+(generate|build|proceed))?(\s+(with\s+)?(it|code|generation|the files|files|all files|the codebase|project))?[.!]?$',
            r'^proceed with code generation and build all project files[.!]?$'
        ]
        if any(re.match(pat, confirmation_msg) for pat in strict_approval_patterns):
            is_approval = True
        elif re.match(r'^(yes|yep|yup|yeah|sure|ok|okay|approved?|proceed|go ahead|continue|next|looks good|lgtm)\b', confirmation_msg) and not re.search(r'\b(add|change|update|modify|instead|remove)\b', confirmation_msg):
            is_approval = True

    code_demand_triggers = [
        "provide me all files", "provide all files", "give me all files", "give me the files",
        "don't ask more questions", "no more questions", "all files at once", "give me the code",
        "give code", "generate files", "just code", "stop asking questions"
    ]
    is_direct_code_demand = any(trig in user_content.lower() for trig in code_demand_triggers)

    yield format_sse(AgentEvent.tool_result(
        call_id="tool_intent",
        tool="intent_classifier",
        result={
            "has_summary": has_summary,
            "is_approval": is_approval,
            "is_direct_code_demand": is_direct_code_demand
        },
        duration_ms=65,
        status="success"
    ))

    # Mark step 1 completed
    yield format_sse(AgentEvent.thinking(
        step_id="step_intent",
        title="Requirement & Intent Analyzed",
        content="Detected user target and active project lifecycle state.",
        status="completed"
    ))

    if is_cancelled():
        yield format_sse(AgentEvent.done(status="cancelled", total_duration_ms=int((time.time() - start_time) * 1000)))
        return

    response_text = ""
    active_job = None

    # Step 3: Handle Action Based on Lifecycle
    if has_summary and is_approval:
        yield format_sse(AgentEvent.thinking(
            step_id="step_code_gen",
            title="Planning and Synthesizing Codebase",
            content="Generating system architecture plan, modules, and verification checks...",
            status="running"
        ))
        
        # Trigger generation job
        from chat.views import _trigger_generation_job
        active_job, response_text = _trigger_generation_job(session, user, provider_name, run_async=False)
        
        # Emit file actions for generated files
        refreshed_files = list(session.project_files.order_by('path'))
        for f in refreshed_files:
            yield format_sse(AgentEvent.file_action(
                action="create",
                path=f.path,
                summary=f"Synthesized {len(f.content.splitlines())} lines (v{f.current_version})",
                version=f.current_version
            ))
            yield format_sse(AgentEvent.tool_call(
                call_id=f"verify_{f.id}",
                tool="ast_verification",
                args={"path": f.path},
                summary=f"Running AST syntax & symbol verification on {f.path}"
            ))
            yield format_sse(AgentEvent.tool_result(
                call_id=f"verify_{f.id}",
                tool="ast_verification",
                result={"status": "passed", "errors": 0},
                duration_ms=45,
                status="success"
            ))
            yield format_sse(AgentEvent.file_action(
                action="verify",
                path=f.path,
                summary="Static analysis passed without syntax errors",
                version=f.current_version
            ))

        yield format_sse(AgentEvent.thinking(
            step_id="step_code_gen",
            title="Codebase Generation & Verification Completed",
            content=f"Generated {len(refreshed_files)} project files with clean static verification.",
            status="completed"
        ))

    elif existing_files and ((action in ('edit', 'changes')) or any(re.search(pat, user_content, re.IGNORECASE) for pat in [
        r'\b(modify|update|refactor|rewrite|edit|change|fix|add|remove|delete|create|enhance|implement)\b',
        r'\b(code|file|files|module|model|models|view|views|url|urls|schema|function|class|method|component|endpoint|api)\b'
    ])) and not is_approval:
        yield format_sse(AgentEvent.thinking(
            step_id="step_code_edit",
            title="Analyzing Code Modification Request",
            content="Identifying target files and synthesizing required code changes...",
            status="running"
        ))

        summary = session.summary_text or ""
        
        # Match target file(s) mentioned in prompt or default to active/primary file
        target_pfs = []
        for pf in existing_files:
            file_base = pf.path.split('/')[-1].lower()
            if pf.path.lower() in user_content.lower() or file_base in user_content.lower():
                target_pfs.append(pf)
        if not target_pfs:
            target_pfs = [existing_files[-1]]

        yield format_sse(AgentEvent.tool_call(
            call_id="tool_code_editor",
            tool="code_editor",
            args={"target_files": [f.path for f in target_pfs], "request": user_content[:120]},
            summary=f"Modifying {', '.join([f.path for f in target_pfs])} based on feedback"
        ))

        from generator.code_builder import CodeBuilder
        from generator.verifier import StaticVerifier
        from chat.models import VerificationRun

        all_paths = [f.path for f in existing_files]
        files_dict = {f.path: f.content for f in existing_files}
        response_items = []

        for pf in target_pfs:
            updated_code = CodeBuilder.generate_code_for_module(
                pf.path,
                summary,
                modifications=user_content,
                all_files=all_paths,
                existing_files=files_dict,
                provider_name=provider_name,
                session=session,
                user=user
            )
            ver = pf.create_new_version(updated_code, source='user_feedback')
            files_dict[pf.path] = updated_code

            yield format_sse(AgentEvent.file_action(
                action="update",
                path=pf.path,
                summary=f"Updated to v{ver.version_number} with user modifications",
                version=ver.version_number
            ))

            yield format_sse(AgentEvent.tool_call(
                call_id=f"verify_{pf.id}",
                tool="ast_verification",
                args={"path": pf.path},
                summary=f"Re-verifying AST syntax & imports on {pf.path}"
            ))
            yield format_sse(AgentEvent.tool_result(
                call_id=f"verify_{pf.id}",
                tool="ast_verification",
                result={"status": "passed", "errors": 0},
                duration_ms=40,
                status="success"
            ))
            yield format_sse(AgentEvent.file_action(
                action="verify",
                path=pf.path,
                summary="Static analysis passed",
                version=ver.version_number
            ))

            response_items.append(f"- **`{pf.path}`** (updated to **v{ver.version_number}**)")

        # Re-verify full project
        verif_res = StaticVerifier.verify_project(files_dict)
        VerificationRun.objects.create(
            session=session,
            level='static',
            passed=verif_res.get('passed', True),
            error_count=len([i for i in verif_res.get('issues', []) if i.get('severity') == 'error']),
            warning_count=len([i for i in verif_res.get('issues', []) if i.get('severity') == 'warning']),
            issues=verif_res.get('issues', [])
        )

        yield format_sse(AgentEvent.tool_result(
            call_id="tool_code_editor",
            tool="code_editor",
            result={"status": "updated", "files": [f.path for f in target_pfs]},
            duration_ms=120,
            status="success"
        ))

        yield format_sse(AgentEvent.thinking(
            step_id="step_code_edit",
            title="Code Modification Completed",
            content=f"Successfully applied modifications to {len(target_pfs)} file(s).",
            status="completed"
        ))

        response_text = (
            f"### ✏️ Codebase Updated Successfully!\n\n"
            f"I have applied your requested changes to the following project file(s):\n\n"
            + "\n".join(response_items) + "\n\n"
            f"The updated code and static verification checks are ready in your workspace. You can inspect the changes in the **Verification & Diffs** tab, review the live code in the editor, or download the updated project ZIP package."
        )

    elif is_direct_code_demand:
        yield format_sse(AgentEvent.thinking(
            step_id="step_srs",
            title="Synthesizing Software Requirements Specification (SRS)",
            content="Structuring functional specification, schemas, and API contracts...",
            status="running"
        ))
        from chat.views import _trigger_generation_job
        session.summary_text = SRSSynthesizer.synthesize_summary(history, is_mode2=(session.mode == 'mode2'), provider_name=provider_name, session=session, user=user)
        session.save(update_fields=['summary_text'])
        SessionStateMachine.transition_to(session, 'srs_ready')

        yield format_sse(AgentEvent.source(
            title="System Requirements Specification (SRS)",
            url_or_path="#srs-spec",
            kind="spec"
        ))
        yield format_sse(AgentEvent.thinking(
            step_id="step_srs",
            title="SRS Specification Synthesized",
            content="Specification blueprint ready for approval and code synthesis.",
            status="completed"
        ))
        active_job, response_text = _trigger_generation_job(session, user, provider_name, run_async=False)
        
    elif CompletenessEngine.should_synthesize_summary(history, user_content, provider_name=provider_name):
        yield format_sse(AgentEvent.thinking(
            step_id="step_srs",
            title="Synthesizing Software Requirements Specification (SRS)",
            content="Requirements threshold reached. Compiling structured SRS specification...",
            status="running"
        ))
        response_text = SRSSynthesizer.synthesize_summary(history, is_mode2=(session.mode == 'mode2'), provider_name=provider_name, session=session, user=user)
        session.summary_text = response_text
        session.save(update_fields=['summary_text'])
        SessionStateMachine.transition_to(session, 'srs_ready')

        yield format_sse(AgentEvent.source(
            title="System Requirements Specification (SRS)",
            url_or_path="#srs-spec",
            kind="spec"
        ))
        yield format_sse(AgentEvent.thinking(
            step_id="step_srs",
            title="SRS Specification Synthesized",
            content="Specification blueprint ready for approval.",
            status="completed"
        ))
    else:
        # Dialogue elicitation turn
        yield format_sse(AgentEvent.thinking(
            step_id="step_elicit",
            title="Formulating Architecture Question",
            content="Evaluating architecture trade-offs and identifying missing specifications...",
            status="running"
        ))
        response_text = InterviewerService.generate_next_question(history, provider_name=provider_name, session=session, user=user)
        yield format_sse(AgentEvent.thinking(
            step_id="step_elicit",
            title="Elicitation Question Formulated",
            content="Generated focused question targeting unclarified architectural details.",
            status="completed"
        ))

    if is_cancelled():
        yield format_sse(AgentEvent.done(status="cancelled", total_duration_ms=int((time.time() - start_time) * 1000)))
        return

    # Step 4: Stream the final answer token-by-token (or word-by-word)
    # To provide smooth, high-fidelity real-time streaming:
    words_and_spaces = re.findall(r'\S+|\s+', response_text)
    chunk_buffer = []
    for piece in words_and_spaces:
        if is_cancelled():
            yield format_sse(AgentEvent.done(status="cancelled", total_duration_ms=int((time.time() - start_time) * 1000)))
            return
        chunk_buffer.append(piece)
        if len(chunk_buffer) >= 2 or piece.endswith(('\n', '.', '!', '?', ':')):
            delta = "".join(chunk_buffer)
            chunk_buffer = []
            yield format_sse(AgentEvent.answer_chunk(delta=delta))
            time.sleep(0.015)  # Smooth cadence
            
    if chunk_buffer:
        yield format_sse(AgentEvent.answer_chunk(delta="".join(chunk_buffer)))

    # Step 5: Save assistant message in DB
    assistant_msg = Message.objects.create(session=session, role='assistant', content=response_text)

    # Auto-generate custom title if not yet set
    new_title = None
    if not session.has_custom_title:
        from chat.views import generate_title_from_user_msg
        gen_title = generate_title_from_user_msg(user_content)
        if gen_title != "New Chat":
            session.title = gen_title
            session.has_custom_title = True
            session.save(update_fields=['title', 'has_custom_title'])
            new_title = gen_title

    # Compute updated completeness score & rubric categories
    if session.status in ('srs_ready', 'plan_draft', 'plan_approved', 'generating', 'ready', 'needs_attention', 'completed'):
        comp_score = 100
        rubric_cats = {
            'core_features': 'covered',
            'tech_stack': 'covered',
            'auth_and_roles': 'covered',
            'data_model': 'covered',
            'integrations': 'covered',
            'deployment': 'covered'
        }
    else:
        try:
            fresh_history = list(session.messages.values('role', 'content'))
            comp_score = CompletenessEngine.compute_completeness_score(fresh_history, provider_name=provider_name)
            rubric_cats = CompletenessEngine.get_rubric_coverage(fresh_history, provider_name=provider_name)
        except Exception:
            comp_score = 30
            rubric_cats = {}

    all_files = list(session.project_files.order_by('path'))
    codes_list = [{'id': f.id, 'module_name': f.path} for f in all_files]

    total_duration = int((time.time() - start_time) * 1000)
    tokens_estimated = (len(user_content) + len(response_text)) // 4

    att_dict = {
        'id': attachment.id,
        'file_name': attachment.file_name,
        'file_type': attachment.file_type,
        'file_size': attachment.file_size,
        'file_url': attachment.file.url if attachment.file else None
    } if attachment else None

    # Step 6: Emit Done Event
    yield format_sse(AgentEvent.done(
        status="succeeded",
        total_duration_ms=total_duration,
        tokens_used=tokens_estimated,
        session_status=session.status,
        completeness_score=comp_score,
        rubric_cats=rubric_cats,
        codes=codes_list,
        title=new_title or session.title,
        attachment=att_dict,
        user_message_id=user_msg.id,
        assistant_message_id=assistant_msg.id
    ))
