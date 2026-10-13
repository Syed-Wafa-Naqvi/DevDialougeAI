from django.test import TestCase, override_settings
from generator.path_safety import PathSafetyManager, PathSafetyError
from generator.protocol import EditProtocolEngine, ProtocolValidationError
from generator.planner import PlanValidator, PlanGenerator, PlanValidationError
from generator.diffing import DiffEngine
from generator.runtime_verifier import RuntimeVerifier
from chat.models import Session, ProjectFile, FileVersion, ProjectPlan
from django.contrib.auth import get_user_model

User = get_user_model()

class Phase1ProtocolAndWorkspaceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='Password123!')
        self.session = Session.objects.create(user=self.user, title="Test Session")

    def test_path_safety_valid(self):
        self.assertEqual(PathSafetyManager.validate_path("todo/models.py"), "todo/models.py")
        self.assertEqual(PathSafetyManager.validate_path("static/css/style.css"), "static/css/style.css")
        self.assertEqual(PathSafetyManager.validate_path("Dockerfile"), "Dockerfile")

    def test_path_safety_prohibited_paths(self):
        # Path traversal
        with self.assertRaises(PathSafetyError):
            PathSafetyManager.validate_path("../etc/passwd")

        with self.assertRaises(PathSafetyError):
            PathSafetyManager.validate_path("todo/../../secret.txt")

        # Absolute paths
        with self.assertRaises(PathSafetyError):
            PathSafetyManager.validate_path("/etc/passwd")

        # Disallowed extensions
        with self.assertRaises(PathSafetyError):
            PathSafetyManager.validate_path("executable.exe")

        # Null bytes
        with self.assertRaises(PathSafetyError):
            PathSafetyManager.validate_path("test.py\x00.exe")

    def test_path_safety_file_size_and_count_limits(self):
        oversized = "a" * (201 * 1024)
        with self.assertRaises(PathSafetyError):
            PathSafetyManager.validate_file_content(oversized)

        with self.assertRaises(PathSafetyError):
            PathSafetyManager.validate_project_file_count(60)

    def test_edit_protocol_json_strip_fences(self):
        raw_json = "```json\n{\"summary\": \"Created models\", \"operations\": []}\n```"
        data = EditProtocolEngine.parse_payload(raw_json)
        self.assertEqual(data["summary"], "Created models")

    def test_replace_in_file_exact_matches(self):
        files = {"todo/views.py": "def foo():\n    pass\n"}

        # 1 match (valid)
        payload = {
            "summary": "Updated view",
            "operations": [
                {"op": "replace_in_file", "path": "todo/views.py", "old": "pass", "new": "return True"}
            ]
        }
        validated = EditProtocolEngine.validate_operations(payload, files)
        updated = EditProtocolEngine.apply_operations_atomically(validated, files)
        self.assertEqual(updated["todo/views.py"], "def foo():\n    return True\n")

        # 0 matches (invalid)
        payload_0 = {
            "summary": "Update missing text",
            "operations": [
                {"op": "replace_in_file", "path": "todo/views.py", "old": "nonexistent_text", "new": "bar"}
            ]
        }
        with self.assertRaises(ProtocolValidationError):
            EditProtocolEngine.validate_operations(payload_0, files)

        # 2 matches (invalid)
        files_multi = {"todo/views.py": "pass\npass\n"}
        payload_2 = {
            "summary": "Update ambiguous text",
            "operations": [
                {"op": "replace_in_file", "path": "todo/views.py", "old": "pass", "new": "bar"}
            ]
        }
        with self.assertRaises(ProtocolValidationError):
            EditProtocolEngine.validate_operations(payload_2, files_multi)

    def test_atomic_apply_rollback_on_failure(self):
        files = {"todo/models.py": "class Task:\n    pass\n"}
        payload = {
            "summary": "Batch ops with one failure",
            "operations": [
                {"op": "create_file", "path": "todo/forms.py", "content": "# forms"},
                {"op": "replace_in_file", "path": "todo/models.py", "old": "INVALID_OLD_TEXT", "new": "# new"}
            ]
        }

        # Should fail atomically without applying any operations
        with self.assertRaises(ProtocolValidationError):
            EditProtocolEngine.validate_operations(payload, files)

        # Confirm original files dict remains untouched
        self.assertNotIn("todo/forms.py", files)
        self.assertEqual(files["todo/models.py"], "class Task:\n    pass\n")

    def test_versioned_project_file_workspace(self):
        pf = ProjectFile.objects.create(session=self.session, path="todo/models.py", content="class Task: pass", current_version=1)
        fv1 = FileVersion.objects.create(project_file=pf, version_number=1, content="class Task: pass", source='generate')

        v2 = pf.create_new_version("class Task:\n    title = models.CharField(max_length=100)", source='user_feedback')
        self.assertEqual(pf.current_version, 2)
        self.assertEqual(pf.content, "class Task:\n    title = models.CharField(max_length=100)")
        self.assertEqual(pf.versions.count(), 2)

    def test_diff_engine(self):
        old_text = "line 1\nline 2\n"
        new_text = "line 1\nline 2 updated\n"
        diff = DiffEngine.generate_unified_diff(old_text, new_text, from_label="v1", to_label="v2")
        self.assertIn("-line 2", diff)
        self.assertIn("+line 2 updated", diff)


class Phase2PlannerTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='planner_user', email='planner@example.com', password='Password123!')
        self.session = Session.objects.create(user=self.user, title="Planner Session", status='interviewing')

    def test_valid_plan_topological_sort(self):
        valid_plan = {
            "project_name": "task_manager",
            "files": [
                {"path": "todo/views.py", "purpose": "Views", "depends_on": ["todo/models.py"], "exports": [{"name": "views_fn"}]},
                {"path": "todo/models.py", "purpose": "Models", "depends_on": [], "exports": [{"name": "Task"}]}
            ],
            "check_commands": ["python manage.py check", "malicious_command"],
            "test_commands": ["python manage.py test"]
        }
        res = PlanValidator.validate_and_sort_plan(valid_plan)
        order = res['generation_order']
        self.assertEqual(order, ["todo/models.py", "todo/views.py"])
        # Disallowed command must be dropped
        self.assertEqual(res['clean_plan']['check_commands'], ["python manage.py check"])

    def test_plan_dependency_cycle_detection(self):
        cycle_plan = {
            "project_name": "cycle_app",
            "files": [
                {"path": "a.py", "purpose": "A", "depends_on": ["b.py"]},
                {"path": "b.py", "purpose": "B", "depends_on": ["a.py"]}
            ]
        }
        from generator.planner import PlanValidationError
        with self.assertRaises(PlanValidationError):
            PlanValidator.validate_and_sort_plan(cycle_plan)

    def test_plan_missing_dependency(self):
        missing_dep_plan = {
            "project_name": "missing_app",
            "files": [
                {"path": "views.py", "purpose": "Views", "depends_on": ["nonexistent_models.py"]}
            ]
        }
        from generator.planner import PlanValidationError
        with self.assertRaises(PlanValidationError):
            PlanValidator.validate_and_sort_plan(missing_dep_plan)

    def test_plan_generator_mock(self):
        from generator.planner import PlanGenerator
        plan_obj = PlanGenerator.generate_plan("Build a todo app in Django", self.session, provider_name='free')
        self.assertIsNotNone(plan_obj)
        self.assertEqual(plan_obj.status, 'draft')
        self.assertIn("todo/models.py", plan_obj.generation_order)

    def test_state_machine_transitions(self):
        from chat.state_machine import SessionStateMachine, InvalidStateTransitionError
        
        # Valid transition: interviewing -> srs_ready
        SessionStateMachine.transition_to(self.session, 'srs_ready')
        self.assertEqual(self.session.status, 'srs_ready')

        # Valid transition: srs_ready -> plan_draft
        SessionStateMachine.transition_to(self.session, 'plan_draft')
        self.assertEqual(self.session.status, 'plan_draft')

        # Invalid transition: plan_draft -> completed
        with self.assertRaises(InvalidStateTransitionError):
            SessionStateMachine.transition_to(self.session, 'completed')


class Phase3VerifierTestCase(TestCase):
    def test_clean_project_zero_errors(self):
        from generator.verifier import StaticVerifier
        clean_files = {
            "todo/models.py": "from django.db import models\nclass Task(models.Model):\n    title = models.CharField(max_length=100)\n",
            "todo/views.py": "from django.shortcuts import render\nfrom .models import Task\ndef task_list(request):\n    tasks = Task.objects.all()\n    return render(request, 'todo/list.html', {'tasks': tasks})\n",
            "todo/templates/todo/list.html": "<h1>Task List</h1>",
            "requirements.txt": "django>=5.0\n"
        }
        res = StaticVerifier.verify_project(clean_files)
        self.assertTrue(res['passed'])
        self.assertEqual(res['error_count'], 0)

    def test_broken_syntax_fixture(self):
        from generator.verifier import StaticVerifier
        broken_files = {
            "bad_syntax.py": "def foo(:\n    pass\n"
        }
        res = StaticVerifier.verify_project(broken_files)
        self.assertFalse(res['passed'])
        self.assertGreaterEqual(res['error_count'], 1)
        self.assertEqual(res['issues'][0]['check'], 'syntax')

    def test_broken_import_and_missing_template(self):
        from generator.verifier import StaticVerifier
        broken_files = {
            "views.py": "from django.shortcuts import render\nfrom .models import NonExistentModel\ndef my_view(request):\n    return render(request, 'missing_template.html', {})\n",
            "models.py": "class ExistingModel:\n    pass\n"
        }
        res = StaticVerifier.verify_project(broken_files)
        self.assertFalse(res['passed'])
        checks = [i['check'] for i in res['issues']]
        self.assertIn('local_import_resolution', checks)
        self.assertIn('missing_template', checks)

    def test_broken_contract_export(self):
        from generator.verifier import StaticVerifier
        files = {
            "todo/models.py": "class Task:\n    pass\n"
        }
        plan_data = {
            "files": [
                {"path": "todo/models.py", "exports": [{"name": "MissingClass"}]}
            ]
        }
        res = StaticVerifier.verify_project(files, plan_data)
        self.assertFalse(res['passed'])
        self.assertIn('contract', [i['check'] for i in res['issues']])

    def test_unresolved_url_view(self):
        from generator.verifier import StaticVerifier
        files = {
            "urls.py": "from django.urls import path\nurlpatterns = [path('items/', nonexistent_view_func)]\n"
        }
        res = StaticVerifier.verify_project(files)
        self.assertFalse(res['passed'])
        self.assertIn('unresolved_url_view', [i['check'] for i in res['issues']])


class Phase4RepairLoopTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='repair_user', email='repair@example.com', password='Password123!')
        self.session = Session.objects.create(user=self.user, title="Repair Session", status='verifying')

    def test_repair_loop_one_attempt_success(self):
        from generator.repair import CodeRepairEngine
        broken_files = {
            "bad_syntax.py": "def foo(:\n    pass\n"
        }
        res = CodeRepairEngine.run_repair_loop(self.session, broken_files, max_attempts=3, provider_name='free')
        self.assertEqual(res['status'], 'verified')
        self.assertEqual(res['attempts'], 1)
        self.assertIn("Static verification passed after 1 repair loop", res['honest_message'])
        self.assertEqual(res['files']['bad_syntax.py'], "def foo():\n    pass\n")

    def test_repair_loop_no_progress_stop(self):
        from generator.repair import CodeRepairEngine
        
        # Unfixable file (mock returns invalid payload for this path)
        broken_files = {
            "unfixable.py": "def unfixable_fn(:\n    pass\n"
        }
        res = CodeRepairEngine.run_repair_loop(self.session, broken_files, max_attempts=3, provider_name='free')
        self.assertEqual(res['status'], 'needs_attention')
        self.assertIn("remain", res['honest_message'].lower())

    def test_repair_loop_honest_message_formatting(self):
        from generator.repair import CodeRepairEngine
        files = {"ok.py": "x = 1\n"}
        res = CodeRepairEngine.run_repair_loop(self.session, files, max_attempts=3, provider_name='free')
        self.assertEqual(res['status'], 'verified')
        self.assertIn("Runtime checks were not run", res['honest_message'])


class Phase5JobsEngineTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='job_user', email='job@example.com', password='Password123!')
        self.session = Session.objects.create(user=self.user, title="Job Session", status='srs_ready')

    def test_job_concurrency_guard(self):
        from generator.jobs import JobExecutionEngine, JobConcurrencyError
        job1 = JobExecutionEngine.create_job(self.session, self.user, 'plan')
        self.assertEqual(job1.status, 'queued')

        # Creating 2nd active job for same session must raise JobConcurrencyError
        with self.assertRaises(JobConcurrencyError):
            JobExecutionEngine.create_job(self.session, self.user, 'generate')

    def test_job_event_sequence_numbers(self):
        from generator.jobs import JobExecutionEngine
        job = JobExecutionEngine.create_job(self.session, self.user, 'plan')
        e1 = job.log_event('info', 'First event')
        e2 = job.log_event('file_started', 'Second event')
        self.assertEqual(e1.sequence_number, 1)
        self.assertEqual(e2.sequence_number, 2)

    def test_job_cancellation(self):
        from generator.jobs import JobExecutionEngine
        job = JobExecutionEngine.create_job(self.session, self.user, 'generate')
        job.cancel_requested = True
        job.save()

        executed = JobExecutionEngine.run_job(job.id, provider_name='free')
        self.assertEqual(executed.status, 'cancelled')

    def test_plan_job_eager_execution(self):
        from generator.jobs import JobExecutionEngine
        job = JobExecutionEngine.create_job(self.session, self.user, 'plan')
        executed = JobExecutionEngine.run_job(job.id, provider_name='free')
        self.assertEqual(executed.status, 'succeeded')
        self.assertEqual(executed.events.count(), 3)


class Phase6ContextAndRubricTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='context_user', email='context@example.com', password='Password123!')
        self.session = Session.objects.create(user=self.user, title="Context Session", status='interviewing')

    def test_rubric_score_computation_in_code(self):
        from dialogue.completeness import CompletenessEngine
        history = [{'role': 'user', 'content': 'I want a Django app with PostgreSQL'}]
        eval_res = CompletenessEngine.evaluate_rubric(history, provider_name='free')
        self.assertIn('score', eval_res)
        # Check calculation: covered core_features(0.25*0.5=0.125) + tech_stack(0.15) + purpose(0.10) = ~23%
        self.assertGreater(eval_res['score'], 0)
        self.assertFalse(eval_res['is_estimated'])

    def test_rubric_keyword_fallback(self):
        from dialogue.completeness import CompletenessEngine
        # Force exception path by testing fallback method directly
        history = [{'role': 'user', 'content': 'I want a Python Django REST API'}]
        score = CompletenessEngine._calculate_keyword_fallback_score(history)
        self.assertGreaterEqual(score, 40)

    def test_context_builder_budget_respected(self):
        from llm_engine.context import ContextBuilder
        from chat.models import Message

        # Add 12 conversation messages
        for i in range(12):
            Message.objects.create(session=self.session, role='user' if i % 2 == 0 else 'assistant', content=f"Message turn #{i} with extra text")

        ctx = ContextBuilder.build_context(self.session, purpose='chat', task_prompt='Build app', model_id='default', provider_name='free')
        self.assertIn('assembled_prompt', ctx)
        self.assertLessEqual(ctx['token_count'], 8000)
        self.assertIn("Message turn #", ctx['assembled_prompt'])

    def test_refresh_conversation_summary(self):
        from llm_engine.context import ContextBuilder
        from chat.models import Message

        for i in range(10):
            Message.objects.create(session=self.session, role='user' if i % 2 == 0 else 'assistant', content=f"Technical statement #{i}")

        summary = ContextBuilder.refresh_conversation_summary(self.session, provider_name='free')
        self.session.refresh_from_db()
        self.assertTrue(len(self.session.summary_text) > 0)


class Phase7RuntimeChecksTestCase(TestCase):
    def setUp(self):
        self.normal_user = User.objects.create_user(username='normal_user', email='normal@example.com', password='Password123!')
        self.staff_user = User.objects.create_user(username='staff_user', email='staff@example.com', password='Password123!', is_staff=True)
        self.valid_files = {
            "main.py": "def main():\n    print('Hello World')\n\nif __name__ == '__main__':\n    main()\n"
        }

    @override_settings(RUNTIME_CHECKS_ENABLED=False)
    def test_flag_off_prevents_execution(self):
        res = RuntimeVerifier.run_verification(self.valid_files, user=self.staff_user)
        self.assertFalse(res['executed'])
        self.assertTrue(res['passed'])
        self.assertEqual(res['reason'], 'Runtime checks disabled')

    @override_settings(RUNTIME_CHECKS_ENABLED=True)
    def test_non_staff_user_prevents_execution(self):
        res = RuntimeVerifier.run_verification(self.valid_files, user=self.normal_user)
        self.assertFalse(res['executed'])
        self.assertTrue(res['passed'])
        self.assertEqual(res['reason'], 'Runtime checks restricted to staff users')

    @override_settings(RUNTIME_CHECKS_ENABLED=True)
    def test_staff_user_executes_successfully(self):
        res = RuntimeVerifier.run_verification(self.valid_files, user=self.staff_user)
        self.assertTrue(res['executed'])
        self.assertTrue(res['passed'])
        self.assertEqual(res['error_count'], 0)

    @override_settings(RUNTIME_CHECKS_ENABLED=True)
    def test_environment_stripping(self):
        import os
        os.environ['HOST_SECRET_TOKEN'] = 'super_secret_123'
        try:
            env_check_files = {
                "check_env.py": (
                    "import os\n"
                    "val = os.environ.get('HOST_SECRET_TOKEN')\n"
                    "if val is not None:\n"
                    "    raise ValueError(f'Host secret leaked: {val}')\n"
                )
            }
            res = RuntimeVerifier.run_verification(env_check_files, user=self.staff_user)
            self.assertTrue(res['executed'])
            self.assertTrue(res['passed'], f"Environment stripping failed: {res.get('issues')}")
        finally:
            os.environ.pop('HOST_SECRET_TOKEN', None)

    @override_settings(RUNTIME_CHECKS_ENABLED=True, RUNTIME_CHECKS_TIMEOUT=1)
    def test_timeout_cancellation(self):
        slow_files = {
            "test_slow.py": "import unittest\nimport time\nclass SlowTest(unittest.TestCase):\n    def test_sleep(self):\n        time.sleep(10)\n"
        }
        res = RuntimeVerifier.run_verification(slow_files, user=self.staff_user)
        self.assertTrue(res['executed'])
        self.assertFalse(res['passed'])
        self.assertGreater(res['error_count'], 0)
        self.assertIn("timed out", res['issues'][0]['message'])



    @override_settings(RUNTIME_CHECKS_ENABLED=True)
    def test_missing_package_skipped(self):
        missing_dep_files = {
            "main.py": "import nonexistent_package_xyz_99\n",
            "requirements.txt": "nonexistent-package-xyz-99==1.0.0\n"
        }
        res = RuntimeVerifier.run_verification(missing_dep_files, user=self.staff_user)
        self.assertFalse(res['executed'])
        self.assertTrue(res['passed'])
        self.assertIn("runtime checks skipped: requires nonexistent-package-xyz-99", res['reason'])


from django.test import Client
from chat.models import Job, GeneratedCode, VerificationRun
from generator.jobs import JobExecutionEngine, JobConcurrencyError
from llm_engine.router import LLMRouter, UsageLimitExceededError
from llm_engine.models import LLMCallLog
from exporter.archiver import ZipArchiver
import io
import zipfile

class Phase8SecurityHardeningTestCase(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username='usera', email='usera@example.com', password='Password123!')
        self.user_a.profile.is_verified = True
        self.user_a.profile.save()

        self.user_b = User.objects.create_user(username='userb', email='userb@example.com', password='Password123!')
        self.user_b.profile.is_verified = True
        self.user_b.profile.save()

        self.session_a = Session.objects.create(user=self.user_a, title="User A Session")
        self.code_a = GeneratedCode.objects.create(session=self.session_a, module_name="todo/models.py", code_content="# User A code")
        self.job_a = JobExecutionEngine.create_job(self.session_a, self.user_a, job_type="plan")

        self.client_b = Client()
        self.client_b.force_login(self.user_b)

    def test_idor_protection(self):
        # User B trying to access User A's objects -> HTTP 404
        resp = self.client_b.get(f'/chat/{self.session_a.id}/')
        self.assertEqual(resp.status_code, 404)

        resp = self.client_b.post(f'/api/chat/{self.session_a.id}/send/', {'message': 'hack'}, content_type='application/json')
        self.assertEqual(resp.status_code, 404)

        resp = self.client_b.post(f'/chat/{self.session_a.id}/delete/')
        self.assertEqual(resp.status_code, 404)

        resp = self.client_b.post(f'/chat/{self.session_a.id}/rename/', {'title': 'Hacked'}, content_type='application/json')
        self.assertEqual(resp.status_code, 404)

        resp = self.client_b.get(f'/api/code/{self.code_a.id}/')
        self.assertEqual(resp.status_code, 404)

        resp = self.client_b.get(f'/api/jobs/{self.job_a.id}/events/')
        self.assertEqual(resp.status_code, 404)

        resp = self.client_b.post(f'/api/jobs/{self.job_a.id}/cancel/')
        self.assertEqual(resp.status_code, 404)

        resp = self.client_b.get(f'/api/session/{self.session_a.id}/download/')
        self.assertEqual(resp.status_code, 404)

    def test_api_key_encryption_and_masking(self):
        profile = self.user_a.profile
        raw_key = "sk-proj-1234567890abcdef"
        profile.set_openai_key(raw_key)
        profile.save()

        # Encrypted field is obfuscated/encrypted in storage
        self.assertNotEqual(profile.encrypted_openai_key, raw_key)
        # Decryption restores exact key
        self.assertEqual(profile.get_openai_key(), raw_key)
        # Masking returns last 4 chars preceded by dots
        self.assertEqual(profile.get_masked_openai_key(), "••••••••cdef")

    def test_otp_security_lockout_and_expiry(self):
        profile = self.user_a.profile
        otp = profile.generate_otp()

        # Invalid OTP attempt
        valid, msg = profile.verify_otp_with_reason("000000")
        self.assertFalse(valid)
        self.assertEqual(profile.otp_failed_attempts, 1)

        # Trigger 5 failed attempts lockout
        for _ in range(4):
            profile.verify_otp_with_reason("000000")

        self.assertEqual(profile.otp_failed_attempts, 5)
        self.assertIsNotNone(profile.otp_lockout_until)

        # Blocked during lockout even if correct OTP is supplied
        valid, msg = profile.verify_otp_with_reason(otp)
        self.assertFalse(valid)
        self.assertIn("Too many failed verification attempts", msg)

    def test_otp_resend_cooldown(self):
        profile = self.user_a.profile
        profile.generate_otp()
        can_resend, reason = profile.can_resend_otp()
        self.assertFalse(can_resend)
        self.assertIn("Please wait", reason)

    @override_settings(DAILY_USER_TOKEN_LIMIT=1000)
    def test_daily_token_usage_limit(self):
        LLMCallLog.objects.create(
            user=self.user_a,
            purpose='chat',
            provider='mock',
            input_tokens=600,
            output_tokens=500
        )
        with self.assertRaises(UsageLimitExceededError):
            LLMRouter.generate("Hello world", user=self.user_a)

    @override_settings(MAX_CONCURRENT_JOBS_PER_USER=1)
    def test_concurrent_jobs_limit(self):
        session_a2 = Session.objects.create(user=self.user_a, title="Session A2")
        with self.assertRaises(JobConcurrencyError):
            JobExecutionEngine.create_job(session_a2, self.user_a, job_type="plan")

    def test_zip_export_safety_and_verification_report(self):
        VerificationRun.objects.create(
            session=self.session_a,
            level="static",
            passed=True,
            error_count=0,
            warning_count=0,
            issues=[]
        )
        zip_bytes = ZipArchiver.create_project_zip(self.session_a)
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            file_names = zf.namelist()
            self.assertIn("todo/models.py", file_names)
            self.assertIn("README.md", file_names)
            self.assertIn("VERIFICATION.md", file_names)

            verif_content = zf.read("VERIFICATION.md").decode('utf-8')
            self.assertIn("Verification Report", verif_content)
            self.assertIn("Status**: PASSED", verif_content)


from django.core.management import call_command
from django.conf import settings
import glob
import os
import json

class Phase9EvaluationBenchmarkTestCase(TestCase):


    def test_run_benchmark_management_command(self):
        call_command('run_benchmark', specs='01_todo_app', provider='mock')

        results_dir = os.path.join(settings.BASE_DIR, 'benchmarks', 'results')
        json_files = glob.glob(os.path.join(results_dir, 'benchmark_*.json'))
        csv_files = glob.glob(os.path.join(results_dir, 'benchmark_*.csv'))

        self.assertGreater(len(json_files), 0)
        self.assertGreater(len(csv_files), 0)

        latest_json = sorted(json_files)[-1]
        with open(latest_json, 'r', encoding='utf-8') as f:
            payload = json.load(f)

        self.assertEqual(payload['provider'], 'mock')
        self.assertIn('summary', payload)
        self.assertIn('results', payload)
        self.assertEqual(len(payload['results']), 1)
        self.assertEqual(payload['results'][0]['spec_name'], '01_todo_app')

    def test_benchmark_comparison_flag(self):
        call_command('run_benchmark', specs='01_todo_app', provider='mock')
        results_dir = os.path.join(settings.BASE_DIR, 'benchmarks', 'results')
        json_files = sorted(glob.glob(os.path.join(results_dir, 'benchmark_*.json')))
        baseline_file = json_files[-1]

        call_command('run_benchmark', specs='01_todo_app', provider='mock', compare=baseline_file)








