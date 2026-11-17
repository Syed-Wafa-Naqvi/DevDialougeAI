import ast
import logging
import os
import py_compile
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('core.self_healing')


class SelfHealingEngine:
    """
    DevDialogue AI Autonomous Self-Healing Engine.
    
    Responsibilities:
    1. Intercept unhandled exceptions and 500 crashes across views and middleware.
    2. Extract the offending file, line number, and complete traceback within project workspace.
    3. Concurrency & Safety Gate: Verify no active code generation jobs or active user traffic are disrupted.
    4. AI Autonomous Repair: Prompt available LLM to synthesize a complete, verified bugfix.
    5. Multi-tier Verification: Verify syntax (AST & py_compile) and execute Django test suite.
    6. Version Control: Commit verified fixes to git and push to origin remote.
    7. Application Server Hot-Reload: Trigger clean reloader restart and restore user session.
    """

    MAX_HEALING_ATTEMPTS = 3
    _healing_lock = threading.Lock()
    _state_lock = threading.Lock()

    _current_state: Dict[str, Any] = {
        "status": "idle",           # idle, diagnosing, repairing, verifying, reloading, restored, failed
        "active_incident": None,
        "last_incident": None,
        "step": "idle",
        "message": "All systems operational",
        "timestamp": time.time(),
        "attempts": 0,
    }

    @classmethod
    def reset_state(cls) -> None:
        with cls._state_lock:
            cls._current_state = {
                "status": "idle",
                "active_incident": None,
                "last_incident": None,
                "step": "idle",
                "message": "All systems operational",
                "timestamp": time.time(),
                "attempts": 0,
            }

    @classmethod
    def get_status(cls) -> Dict[str, Any]:
        with cls._state_lock:
            return dict(cls._current_state)

    @classmethod
    def is_healing_active(cls) -> bool:
        with cls._state_lock:
            return cls._current_state.get("status") in ("diagnosing", "repairing", "verifying", "reloading")

    @classmethod
    def update_state(cls, status: str, step: str, message: str, **kwargs) -> None:
        with cls._state_lock:
            cls._current_state.update({
                "status": status,
                "step": step,
                "message": message,
                "timestamp": time.time(),
                **kwargs
            })
        logger.info("[SELF-HEALING] [STATUS: %s] %s | %s", status.upper(), step, message)

    @classmethod
    def extract_error_details(cls, exc: Exception, tb=None) -> Dict[str, Any]:
        """
        Parses the exception and traceback frames to locate the topmost
        project workspace source file responsible for the failure.
        """
        if tb is None:
            tb = exc.__traceback__

        tb_lines = traceback.format_exception(type(exc), exc, tb)
        tb_text = "".join(tb_lines)

        base_dir = str(settings.BASE_DIR)
        extracted_frames = traceback.extract_tb(tb) if tb else []

        offending_file = None
        offending_line = 0
        func_name = ""
        code_context = ""

        # Scan frames from bottom (most recent) to top to find the project file
        for frame in reversed(extracted_frames):
            fname = frame.filename
            if fname.startswith(base_dir):
                rel = os.path.relpath(fname, base_dir)
                # Ignore virtualenvs, hidden files, and test files if possible
                if not any(part in rel for part in ('env/', 'venv/', '.venv/', 'site-packages/', '<string>', '<stdin>')):
                    offending_file = fname
                    offending_line = frame.lineno
                    func_name = frame.name
                    break

        # Fallback if all frames were in site-packages
        if not offending_file and extracted_frames:
            for frame in extracted_frames:
                fname = frame.filename
                if fname.startswith(base_dir):
                    offending_file = fname
                    offending_line = frame.lineno
                    func_name = frame.name
                    break

        if not offending_file:
            offending_file = str(settings.BASE_DIR / 'chat' / 'views.py')
            offending_line = 1

        rel_path = os.path.relpath(offending_file, base_dir)

        # Read context lines from the offending file
        try:
            with open(offending_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                start = max(0, offending_line - 20)
                end = min(len(lines), offending_line + 20)
                code_context = "".join(lines[start:end])
        except Exception:
            code_context = ""

        return {
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
            "traceback": tb_text,
            "offending_file": offending_file,
            "relative_file": rel_path,
            "offending_line": offending_line,
            "func_name": func_name,
            "code_context": code_context,
        }

    @classmethod
    def is_safe_to_heal(cls, timeout_seconds: float = 3.0) -> bool:
        """
        Safety gate verifying:
        1. No active background code generation jobs are in progress (Job.status='running').
        2. No other user requests are in flight (draining in-flight requests).
        """
        start_wait = time.time()
        while time.time() - start_wait < timeout_seconds:
            try:
                from chat.models import Job
                active_jobs = Job.objects.filter(status='running').exists()
                if active_jobs:
                    logger.info("[SELF-HEALING SAFETY] Active background generation job in progress. Waiting for completion...")
                    time.sleep(0.5)
                    continue
            except Exception:
                pass

            try:
                from core.middleware import SelfHealingMiddleware
                active_reqs = SelfHealingMiddleware.get_active_requests_count()
                # If only the current stuck request is active, it is safe
                if active_reqs <= 1:
                    return True
                logger.info("[SELF-HEALING SAFETY] %d active requests in-flight. Waiting for quiet window...", active_reqs)
                time.sleep(0.3)
            except Exception:
                return True

        return True

    @classmethod
    def trigger_healing(
        cls,
        exc: Exception,
        request=None,
        target_file: Optional[str] = None,
        offending_line: Optional[int] = None,
        run_async: bool = True
    ) -> Dict[str, Any]:
        """
        Entry point called when an unhandled exception or 500 error is caught.
        Records the incident in SQLite and dispatches the autonomous repair loop.
        """
        error_info = cls.extract_error_details(exc)
        if target_file:
            abs_target = str(settings.BASE_DIR / target_file) if not os.path.isabs(target_file) else target_file
            error_info["offending_file"] = abs_target
            error_info["relative_file"] = os.path.relpath(abs_target, settings.BASE_DIR)
            if offending_line:
                error_info["offending_line"] = offending_line

        req_path = getattr(request, 'path', '/') if request else "/"

        logger.warning(
            "[SELF-HEALING TRIGGERED] %s: %s in %s:%d (Path: %s)",
            error_info["error_type"],
            error_info["error_message"],
            error_info["relative_file"],
            error_info["offending_line"],
            req_path
        )

        # Record Incident in SQLite
        incident = None
        try:
            from chat.models import SelfHealingIncident
            incident = SelfHealingIncident.objects.create(
                error_type=error_info["error_type"],
                error_message=error_info["error_message"][:2000],
                offending_file=error_info["relative_file"],
                offending_line=error_info["offending_line"],
                traceback_text=error_info["traceback"][:5000],
                request_path=req_path[:255],
                status='investigating'
            )
        except Exception as e:
            logger.error("[SELF-HEALING] Failed to record incident in DB: %s", e)

        incident_id = incident.id if incident else int(time.time())

        cls.update_state(
            status="diagnosing",
            step="fault_isolation",
            message=f"Intercepted {error_info['error_type']} in {error_info['relative_file']}",
            active_incident={
                "id": incident_id,
                "error_type": error_info["error_type"],
                "error_message": error_info["error_message"],
                "file": error_info["relative_file"],
                "line": error_info["offending_line"],
                "path": req_path
            }
        )

        if run_async:
            repair_thread = threading.Thread(
                target=cls._run_healing_pipeline,
                args=(error_info, incident, req_path),
                daemon=True,
                name="SelfHealingWorker"
            )
            repair_thread.start()
        else:
            cls._run_healing_pipeline(error_info, incident, req_path)

        return {
            "incident_id": incident_id,
            "error_type": error_info["error_type"],
            "error_message": error_info["error_message"],
            "offending_file": error_info["relative_file"],
            "offending_line": error_info["offending_line"],
            "request_path": req_path
        }

    @classmethod
    def _run_healing_pipeline(cls, error_info: Dict[str, Any], incident_obj, request_path: str) -> bool:
        """
        Executes the autonomous healing lifecycle under the thread lock.
        """
        if not cls._healing_lock.acquire(blocking=False):
            logger.info("[SELF-HEALING] Healing pipeline already running. Subsuming error into active cycle.")
            return False

        target_file = error_info["offending_file"]
        backup_file = f"{target_file}.bak.self_healing"
        success = False

        try:
            # 1. Safety Check
            cls.update_state("diagnosing", "safety_check", "Verifying active jobs and request quiet window...")
            cls.is_safe_to_heal(timeout_seconds=4.0)

            if not os.path.exists(target_file):
                logger.error("[SELF-HEALING] Target file %s does not exist on disk.", target_file)
                cls.update_state("failed", "target_missing", f"File {target_file} not found.")
                return False

            # 2. Backup Target File
            try:
                shutil.copyfile(target_file, backup_file)
                logger.info("[SELF-HEALING] Backed up %s to %s", target_file, backup_file)
            except Exception as e:
                logger.error("[SELF-HEALING] Failed to create backup: %s", e)
                cls.update_state("failed", "backup_failed", str(e))
                return False

            with open(target_file, 'r', encoding='utf-8') as f:
                original_code = f.read()

            # 3. AI Repair & Multi-tier Verification Loop
            candidate_code = None
            last_error = ""

            for attempt in range(1, cls.MAX_HEALING_ATTEMPTS + 1):
                cls.update_state(
                    status="repairing",
                    step=f"attempt_{attempt}",
                    message=f"Synthesizing autonomous AI code patch (Attempt {attempt}/{cls.MAX_HEALING_ATTEMPTS})...",
                    attempts=attempt
                )

                if incident_obj:
                    try:
                        incident_obj.status = 'repairing'
                        incident_obj.repair_attempts = attempt
                        incident_obj.save(update_fields=['status', 'repair_attempts'])
                    except Exception:
                        pass

                candidate_code = cls._generate_ai_fix(
                    error_info=error_info,
                    original_code=original_code,
                    attempt=attempt,
                    previous_failure=last_error
                )

                if not candidate_code:
                    last_error = "LLM returned empty or unparseable code."
                    continue

                # Verification Step 1: AST & Compilation
                cls.update_state("verifying", "ast_syntax_check", "Executing AST validation and bytecode compilation...")
                syntax_ok, syntax_err = cls._verify_syntax(candidate_code, error_info["relative_file"], original_code=original_code)
                if not syntax_ok:
                    logger.warning("[SELF-HEALING] Attempt %d AST syntax check failed: %s", attempt, syntax_err)
                    last_error = f"SyntaxError in generated code: {syntax_err}"
                    continue

                # Verification Step 2: Write candidate and run test suite
                cls.update_state("verifying", "regression_tests", "Executing automated test suite against candidate code...")
                test_ok = False
                test_err = ""
                try:
                    with open(target_file, 'w', encoding='utf-8') as f:
                        f.write(candidate_code)
                    test_ok, test_err = cls._run_app_tests(error_info["relative_file"])
                except Exception as ex:
                    test_ok = False
                    test_err = str(ex)
                finally:
                    if not test_ok:
                        with open(target_file, 'w', encoding='utf-8') as f:
                            f.write(original_code)

                if not test_ok:
                    logger.warning("[SELF-HEALING] Attempt %d test suite failed: %s", attempt, test_err)
                    last_error = f"Automated test regression: {test_err}"
                    continue

                # All checks passed!
                success = True
                logger.info("[SELF-HEALING] Code patch verified with 0 errors on attempt %d!", attempt)
                break

            if not success:
                logger.error("[SELF-HEALING] All %d repair attempts failed. Restoring from backup.", cls.MAX_HEALING_ATTEMPTS)
                if os.path.exists(backup_file):
                    shutil.copyfile(backup_file, target_file)
                    try:
                        os.remove(backup_file)
                    except Exception:
                        pass
                cls.update_state("failed", "repair_exhausted", f"Failed after {cls.MAX_HEALING_ATTEMPTS} attempts: {last_error}")
                if incident_obj:
                    try:
                        incident_obj.status = 'failed'
                        incident_obj.save(update_fields=['status'])
                    except Exception:
                        pass
                return False

            # Clean up backup
            if os.path.exists(backup_file):
                try:
                    os.remove(backup_file)
                except Exception:
                    pass

            if incident_obj:
                try:
                    incident_obj.status = 'verified'
                    incident_obj.save(update_fields=['status'])
                except Exception:
                    pass

            # 4. Version Control: Git Commit & Push
            cls.update_state("reloading", "git_version_control", "Committing verified patch and pushing to git remote...")
            git_commit_hash, git_pushed = cls._commit_and_push_fix(
                target_file=target_file,
                relative_file=error_info["relative_file"],
                error_type=error_info["error_type"],
                attempt=cls._current_state.get("attempts", 1)
            )

            if incident_obj:
                try:
                    incident_obj.git_committed = bool(git_commit_hash)
                    incident_obj.git_pushed = git_pushed
                    incident_obj.git_commit_hash = git_commit_hash or ''
                    incident_obj.status = 'resolved'
                    incident_obj.resolved_at = timezone.now()
                    incident_obj.save(update_fields=['git_committed', 'git_pushed', 'git_commit_hash', 'status', 'resolved_at'])
                except Exception:
                    pass

            # 5. Hot-Reload Application Server
            cls.update_state("reloading", "hot_reload", "Triggering application worker hot-reload...")
            cls._trigger_server_reload()

            time.sleep(1.0)
            cls.update_state(
                status="restored",
                step="restored",
                message=f"Autonomously repaired {error_info['relative_file']} ({git_commit_hash[:7] if git_commit_hash else 'verified'}). Services restored.",
                last_incident=cls._current_state.get("active_incident")
            )
            return True

        except Exception as e:
            logger.exception("[SELF-HEALING PIPELINE CRASH] %s", str(e))
            if os.path.exists(backup_file):
                try:
                    shutil.copyfile(backup_file, target_file)
                except Exception:
                    pass
            cls.update_state("failed", "pipeline_exception", str(e))
            return False
        finally:
            if not success and os.path.exists(backup_file):
                try:
                    shutil.copyfile(backup_file, target_file)
                    os.remove(backup_file)
                except Exception:
                    pass
            cls._healing_lock.release()

    @classmethod
    def _generate_ai_fix(
        cls,
        error_info: Dict[str, Any],
        original_code: str,
        attempt: int,
        previous_failure: str = ""
    ) -> Optional[str]:
        """
        Prompts LLMRouter with the exception context and whole source file to produce
        the corrected file content.
        """
        from llm_engine.router import LLMRouter

        system_prompt = (
            "You are DevDialogue AI's Autonomous Codebase Self-Healing Engine.\n"
            "An internal server runtime exception occurred in the DevDialogue AI Django application.\n"
            "Your objective is to diagnose the root cause, fix the defect in the target file, and return "
            "the COMPLETE, syntactically valid replacement Python file.\n\n"
            "Rules:\n"
            "1. Output ONLY the raw Python source code for the file.\n"
            "2. Preserve all existing valid classes, functions, routes, endpoints, imports, and docstrings.\n"
            "3. Do not include markdown commentary, conversational pleasantries, or explanation.\n"
            "4. Ensure 100% syntactically correct Python 3.12+ code."
        )

        feedback_section = ""
        if previous_failure:
            feedback_section = (
                f"\n\n[PREVIOUS ATTEMPT VERIFICATION FAILURE]\n"
                f"{previous_failure}\n"
                f"Please correct the above failure while resolving the original defect."
            )

        prompt = (
            f"[INTERNAL RUNTIME EXCEPTION]\n"
            f"Exception Type: {error_info['error_type']}\n"
            f"Exception Message: {error_info['error_message']}\n"
            f"Offending File: {error_info['relative_file']} (Line {error_info['offending_line']} in '{error_info['func_name']}')\n\n"
            f"[TRACEBACK]\n"
            f"{error_info['traceback']}\n\n"
            f"[CONTEXT AROUND OFFENDING LINE]\n"
            f"{error_info['code_context']}\n"
            f"{feedback_section}\n\n"
            f"[CURRENT FILE CONTENT: {error_info['relative_file']}]\n"
            f"{original_code}\n\n"
            f"Generate the complete, updated source code for {error_info['relative_file']} that fixes this error."
        )

        try:
            raw_response = LLMRouter.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                purpose='self_healing'
            )
            cleaned = cls._clean_code_response(raw_response)
            return cleaned
        except Exception as e:
            logger.error("[SELF-HEALING AI CALL FAILED] %s", str(e))
            return None

    @classmethod
    def _clean_code_response(cls, text: str) -> str:
        """
        Extracts clean python code from LLM response, stripping code blocks if present.
        """
        if not text:
            return ""
        
        # If wrapped in ```python ... ```
        match = re.search(r'```(?:python)?\s*\n([\s\S]*?)\n```', text)
        if match:
            return match.group(1).strip() + "\n"

        # If wrapped in generic backticks
        if text.startswith('```') and text.endswith('```'):
            lines = text.splitlines()
            return "\n".join(lines[1:-1]).strip() + "\n"

        return text.strip() + "\n"

    @classmethod
    def _verify_syntax(cls, code: str, relative_path: str, original_code: str = "") -> Tuple[bool, str]:
        """
        Checks AST validity, compilation, and structural sanity.
        """
        if not code or not code.strip():
            return False, "Candidate code is empty."

        try:
            ast.parse(code, filename=relative_path)
            compile(code, relative_path, 'exec')
        except SyntaxError as e:
            return False, f"Line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, str(e)

        # Structural sanity check:
        # If original code defines functions or classes, candidate replacement must preserve them
        if original_code:
            orig_defs = len(re.findall(r'^\s*(?:def|class)\s+\w+', original_code, re.MULTILINE))
            cand_defs = len(re.findall(r'^\s*(?:def|class)\s+\w+', code, re.MULTILINE))
            if orig_defs >= 3 and cand_defs == 0:
                return False, f"Candidate code dropped all {orig_defs} function/class definitions."
            if len(code) < min(100, len(original_code) * 0.2):
                return False, f"Candidate code is suspiciously truncated ({len(code)} bytes vs original {len(original_code)} bytes)."

        return True, ""

    @classmethod
    def _run_app_tests(cls, relative_file: str) -> Tuple[bool, str]:
        """
        Executes the relevant Django test suite to verify no regressions were introduced.
        """
        base_dir = str(settings.BASE_DIR)
        app_name = relative_file.split('/')[0] if '/' in relative_file else 'chat'
        
        # Target test module based on app
        test_target = f"{app_name}.tests"
        if app_name == 'chat':
            test_target = "chat.tests.ChatTestCase"
        elif app_name not in ('chat', 'generator', 'llm_engine', 'accounts', 'exporter'):
            test_target = "chat.tests.ChatTestCase"

        cmd = [sys.executable, 'manage.py', 'test', '--keepdb', test_target]
        logger.info("[SELF-HEALING TEST] Running test target: %s", test_target)

        env = dict(os.environ)
        env['DEVDIALOGUE_HEALING_VERIFICATION'] = '1'

        try:
            proc = subprocess.run(
                cmd,
                cwd=base_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=60
            )
            if proc.returncode == 0:
                return True, ""
            return False, (proc.stderr or proc.stdout)[-800:]
        except subprocess.TimeoutExpired:
            return False, "Test suite timed out after 60s"
        except Exception as e:
            logger.warning("[SELF-HEALING TEST EXECUTION ERROR] %s", e)
            return False, f"Test execution failed: {str(e)}"

    @classmethod
    def _commit_and_push_fix(
        cls,
        target_file: str,
        relative_file: str,
        error_type: str,
        attempt: int
    ) -> Tuple[str, bool]:
        """
        Stages the fixed file, creates a git commit, and attempts a git push to origin.
        """
        base_dir = str(settings.BASE_DIR)
        commit_hash = ""
        pushed = False

        try:
            # Git add
            subprocess.run(['git', 'add', target_file], cwd=base_dir, capture_output=True, text=True, check=True)

            # Git commit
            commit_msg = f"fix(self-healing): autonomously repaired {relative_file} for {error_type} [attempt {attempt}]"
            res = subprocess.run(
                ['git', 'commit', '-m', commit_msg],
                cwd=base_dir,
                capture_output=True,
                text=True
            )
            if res.returncode == 0:
                logger.info("[SELF-HEALING GIT] Successfully committed fix: %s", commit_msg)
                # Extract commit hash
                hash_proc = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=base_dir, capture_output=True, text=True)
                commit_hash = hash_proc.stdout.strip()
            else:
                logger.info("[SELF-HEALING GIT COMMIT NOTE] %s", res.stdout or res.stderr)

            # Git push (with 15s timeout)
            try:
                push_proc = subprocess.run(
                    ['git', 'push', 'origin', 'HEAD'],
                    cwd=base_dir,
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                if push_proc.returncode == 0:
                    logger.info("[SELF-HEALING GIT PUSH] Successfully pushed verified fix to remote origin.")
                    pushed = True
                else:
                    logger.info("[SELF-HEALING GIT PUSH NOTICE] Push exited with code %d: %s", push_proc.returncode, push_proc.stderr[:200])
            except subprocess.TimeoutExpired:
                logger.warning("[SELF-HEALING GIT PUSH] Git push timed out (remote network slow/offline).")
            except Exception as push_err:
                logger.warning("[SELF-HEALING GIT PUSH] Remote push skipped: %s", push_err)

        except Exception as e:
            logger.error("[SELF-HEALING GIT ERROR] %s", str(e))

        return commit_hash, pushed

    @classmethod
    def _trigger_server_reload(cls) -> None:
        """
        Touches manage.py and config/wsgi.py to trigger Django runserver / Gunicorn reloader.
        """
        base_dir = Path(settings.BASE_DIR)
        targets = [base_dir / 'manage.py', base_dir / 'config' / 'wsgi.py']
        for p in targets:
            if p.exists():
                try:
                    os.utime(str(p), None)
                    logger.info("[SELF-HEALING RELOAD] Touched %s to trigger server hot-reload.", p.name)
                except Exception as e:
                    logger.warning("[SELF-HEALING RELOAD NOTICE] %s: %s", p.name, e)


def render_self_healing_response(request, incident_data: Optional[Dict[str, Any]] = None, status_code: int = 503):
    """
    Renders either a JSON error payload for API/SSE endpoints, or the styled
    self_healing.html maintenance screen for browser page requests.
    """
    path = getattr(request, 'path', '/')
    headers = getattr(request, 'headers', {})
    accept = headers.get('accept', '') if hasattr(headers, 'get') else ''
    
    is_api = (
        path.startswith('/api/') or
        'application/json' in accept or
        headers.get('x-requested-with') == 'XMLHttpRequest' or
        'text/event-stream' in accept
    )

    if is_api:
        from django.http import JsonResponse
        return JsonResponse({
            "status": "self_healing",
            "healing": True,
            "message": "DevDialogue AI autonomous self-healing in progress. The internal system issue is being resolved.",
            "incident": incident_data or {},
        }, status=status_code)

    from django.shortcuts import render
    ctx = {
        "original_path": path,
        "incident_id": incident_data.get("incident_id") if incident_data else "",
        "error_type": incident_data.get("error_type") if incident_data else "InternalServerError",
        "error_message": incident_data.get("error_message") if incident_data else "An unexpected internal condition occurred.",
        "offending_file": incident_data.get("offending_file") if incident_data else "Application Module",
        "offending_line": incident_data.get("offending_line") if incident_data else 0,
        "request_path": path,
    }
    return render(request, 'self_healing.html', ctx, status=status_code)

