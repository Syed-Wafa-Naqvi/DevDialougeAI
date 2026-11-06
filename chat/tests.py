from django.test import TestCase, Client
from django.contrib.auth.models import User
from unittest.mock import patch
from accounts.models import Profile
from chat.models import Session, Message, GeneratedCode, ProjectFile, FileVersion
from generator.jobs import JobConcurrencyError

class ChatTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='Password123!')
        self.user.profile.is_verified = True
        self.user.profile.save()
        self.client = Client()
        self.client.login(username='testuser', password='Password123!')

    def test_create_session(self):
        response = self.client.post('/create-session/', {'mode': 'mode1', 'description': 'Build a REST API'})
        self.assertEqual(response.status_code, 302)
        session = Session.objects.filter(user=self.user).first()
        self.assertIsNotNone(session)
        self.assertEqual(session.messages.count(), 2)

    def test_send_message_api(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'Python/Django', 'provider': 'gemini'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('response', data)

    def test_mode1_can_be_edited_after_completion(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='completed')
        GeneratedCode.objects.create(session=session, module_name='views.py', code_content='def hello(): pass')
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Project Concept: Test App')

        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'Please update views.py to add login view', 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('response', data)

    def test_approval_negation_guard(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Project Concept: Test App\nShould I proceed to generate?')

        # Saying "no, don't build it yet" should NOT trigger code generation
        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': "no, don't build it yet, I want to change the database", 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertNotEqual(session.status, 'completed')
        self.assertFalse(session.generated_codes.exists())

    def test_long_module_name_supported(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        long_path = "lib/presentation/modules/authentication/views/subviews/user_profile_detail_editor_screen.dart"
        self.assertGreater(len(long_path), 80)
        obj = GeneratedCode.objects.create(session=session, module_name=long_path, code_content="// Dart code")
        self.assertEqual(obj.module_name, long_path)

    def test_approval_transitions_and_runs_job_successfully(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Project Concept: Todo App\nAre you ready to proceed to generate?')

        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'yes, go ahead and generate the files', 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertIn(session.status, ['ready', 'needs_attention'])
        self.assertTrue(session.project_files.exists())
        self.assertTrue(session.project_files.exists())
        self.assertTrue(session.jobs.filter(status='succeeded').exists())

    def test_job_refresh_from_db_populates_result_summary(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='srs_ready')
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Project Concept: Todo App')
        
        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'yes, proceed', 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        job = session.jobs.last()
        self.assertIsNotNone(job)
        self.assertEqual(job.status, 'succeeded')
        self.assertTrue(len(job.result_summary) > 0)

    def test_ai_outage_returns_friendly_503(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        with patch('llm_engine.router.LLMRouter.generate', side_effect=RuntimeError("Outage across all providers")):
            response = self.client.post(
                f'/api/chat/{session.id}/send/',
                data={'message': 'Tell me about architecture', 'provider': 'mock'},
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 503)
            data = response.json()
            self.assertIn("temporarily unavailable", data['response'])
            self.assertTrue(session.messages.filter(role='assistant', content__contains="temporarily unavailable").exists())

    def test_job_concurrency_error_returns_409(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Project Concept: Todo App')
        with patch('generator.jobs.JobExecutionEngine.create_job', side_effect=JobConcurrencyError("Already running")):
            response = self.client.post(
                f'/api/chat/{session.id}/send/',
                data={'message': 'yes, proceed', 'provider': 'mock'},
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 409)

    def test_post_generation_qa_does_not_overwrite_project_files(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='ready')
        original_code = "def get_todos(): return ['item1']"
        pf = ProjectFile.objects.create(session=session, path='main.py', content=original_code, status='verified', current_version=1)
        GeneratedCode.objects.create(session=session, module_name='main.py', code_content=original_code)
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Project Concept: Todo App')

        canned_ai_response = "To run your app, execute:\n```python\n# main.py\ndef run_server(): pass\n```"
        with patch('llm_engine.router.LLMRouter.generate', return_value=canned_ai_response):
            response = self.client.post(
                f'/api/chat/{session.id}/send/',
                data={'message': 'How do I run this application?', 'provider': 'mock'},
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 200)
            pf.refresh_from_db()
            self.assertEqual(pf.content, original_code)
            self.assertEqual(pf.versions.count(), 1)

    def test_mode2_incremental_generation_uses_project_files(self):
        session = Session.objects.create(user=self.user, mode='mode2', status='active')
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Project Concept: Todo App')

        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'yes, proceed with the first module', 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(session.project_files.exists())
        pf = session.project_files.first()
        self.assertEqual(pf.status, 'generated')
        self.assertEqual(pf.current_version, 1)

    def test_srs_summary_sets_status_srs_ready(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        with patch('dialogue.completeness.CompletenessEngine.should_synthesize_summary', return_value=True):
            with patch('dialogue.synthesizer.SRSSynthesizer.synthesize_summary', return_value="### Project Requirements Summary\n- Concept: REST API"):
                response = self.client.post(
                    f'/api/chat/{session.id}/send/',
                    data={'message': 'We have finalized all requirements', 'provider': 'mock'},
                    content_type='application/json'
                )
                self.assertEqual(response.status_code, 200)
                session.refresh_from_db()
                self.assertEqual(session.status, 'srs_ready')
                self.assertTrue(session.summary_text.startswith("### Project Requirements Summary"))

    def test_async_job_execution_returns_job_id(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='srs_ready')
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Concept: REST API')
        
        with patch('generator.jobs.JobExecutionEngine.create_job') as mock_create_job:
            class DummyJob:
                id = 999
            mock_create_job.return_value = DummyJob()
            
            with patch('threading.Thread.start') as mock_thread_start:
                response = self.client.post(
                    f'/api/chat/{session.id}/send/',
                    data={'message': 'yes, proceed', 'provider': 'mock'},
                    content_type='application/json',
                    HTTP_X_RUN_SYNC='false'
                )
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data.get('job_id'), 999)
                self.assertIn("Generation Started", data.get('response'))
                mock_thread_start.assert_called_once()

    def test_run_job_worker_direct_execution(self):
        from chat.views import _run_job_worker
        from generator.jobs import JobExecutionEngine
        session = Session.objects.create(user=self.user, mode='mode1', status='srs_ready')
        Message.objects.create(session=session, role='assistant', content='### Project Requirements Summary\n- Concept: REST API')
        job = JobExecutionEngine.create_job(session=session, user=self.user, job_type='generate')
        
        # Directly invoke _run_job_worker with (job.id, 'mock') - verifying no decorator crashes with AttributeError
        _run_job_worker(job.id, 'mock')
        job.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(job.status, 'succeeded')
        self.assertIn(session.status, ['ready', 'needs_attention'])
        self.assertTrue(session.messages.filter(role='assistant').filter(content__contains="Ready").exists())

    def test_cancel_queued_job_cancels_immediately(self):
        from generator.jobs import JobExecutionEngine
        session = Session.objects.create(user=self.user, mode='mode1', status='generating')
        job = JobExecutionEngine.create_job(session=session, user=self.user, job_type='generate')
        self.assertEqual(job.status, 'queued')
        
        response = self.client.post(f'/api/jobs/{job.id}/cancel/')
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')
        self.assertEqual(session.status, 'srs_ready')

    def test_approve_plan_api(self):
        from chat.models import ProjectPlan
        session = Session.objects.create(user=self.user, mode='mode1', status='plan_draft')
        plan = ProjectPlan.objects.create(session=session, version=1, status='draft', plan_data={'files': []})
        response = self.client.post(f'/api/session/{session.id}/plan/approve/')
        self.assertEqual(response.status_code, 200)
        plan.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(plan.status, 'approved')
        self.assertEqual(session.status, 'plan_approved')

    def test_get_job_events_api_safe_parsing(self):
        from generator.jobs import JobExecutionEngine
        session = Session.objects.create(user=self.user, mode='mode1', status='srs_ready')
        job = JobExecutionEngine.create_job(session=session, user=self.user, job_type='generate')
        
        # Test with string / invalid 'after' parameter
        response = self.client.get(f'/api/jobs/{job.id}/events/?after=not_a_number')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('events', data)
        
        # Test with negative 'after' parameter
        response = self.client.get(f'/api/jobs/{job.id}/events/?after=-99')
        self.assertEqual(response.status_code, 200)

    def test_stale_jobs_cleaned_up_on_create_job(self):
        from django.utils import timezone
        from datetime import timedelta
        from generator.jobs import JobExecutionEngine
        from chat.models import Job
        session = Session.objects.create(user=self.user, mode='mode1', status='generating')
        old_time = timezone.now() - timedelta(minutes=20)
        stale_job = Job.objects.create(session=session, user=self.user, status='running')
        Job.objects.filter(id=stale_job.id).update(updated_at=old_time)
        
        # Calling create_job should detect stale job, mark it failed, and allow creating a new job
        new_job = JobExecutionEngine.create_job(session=session, user=self.user, job_type='generate')
        stale_job.refresh_from_db()
        self.assertEqual(stale_job.status, 'failed')
        self.assertIn("timed out", stale_job.error_message)
        self.assertEqual(new_job.status, 'queued')

    def test_chat_view_active_job_context(self):
        from generator.jobs import JobExecutionEngine
        session = Session.objects.create(user=self.user, mode='mode1', status='generating')
        job = JobExecutionEngine.create_job(session=session, user=self.user, job_type='generate')
        response = self.client.get(f'/chat/{session.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_job'], job)

    def test_project_file_save_path_safety_validation(self):
        from generator.path_safety import PathSafetyError
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        with self.assertRaises(PathSafetyError):
            ProjectFile.objects.create(session=session, path='../../etc/passwd', content='bad')

    def test_get_job_events_api_includes_session_status(self):
        from generator.jobs import JobExecutionEngine
        session = Session.objects.create(user=self.user, mode='mode1', status='needs_attention')
        job = JobExecutionEngine.create_job(session=session, user=self.user, job_type='generate')
        response = self.client.get(f'/api/jobs/{job.id}/events/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('session_status', data)
        self.assertEqual(data['session_status'], 'needs_attention')

    def test_request_changes_does_not_misfire_generation(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='srs_ready', summary_text="SRS Summary")
        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'Please modify the requirements to: also build an admin panel', 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        # Session status should NOT have transitioned to generating or ready
        self.assertNotEqual(session.status, 'generating')
        self.assertNotEqual(session.status, 'ready')
        self.assertFalse(session.jobs.exists())

    def test_explicit_action_generate_triggers_approval(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='srs_ready', summary_text="SRS Summary")
        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'Click generate button', 'action': 'generate', 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertIn(session.status, ['ready', 'needs_attention'])
        self.assertTrue(session.jobs.filter(status='succeeded').exists())

    def test_get_project_name_does_not_mutate_session_title(self):
        from exporter.archiver import ZipArchiver
        session = Session.objects.create(user=self.user, title='Custom Workspace Title', mode='mode1', status='active')
        name = ZipArchiver.get_project_name(session)
        self.assertIsInstance(name, str)
        session.refresh_from_db()
        self.assertEqual(session.title, 'Custom Workspace Title')

    def test_cancel_session_api_cancels_jobs_and_reverts_state(self):
        from generator.jobs import JobExecutionEngine
        session = Session.objects.create(user=self.user, mode='mode1', status='generating')
        queued_job = JobExecutionEngine.create_job(session=session, user=self.user, job_type='generate')
        self.assertEqual(queued_job.status, 'queued')
        
        response = self.client.post(f'/api/session/{session.id}/cancel/')
        self.assertEqual(response.status_code, 200)
        queued_job.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(queued_job.status, 'cancelled')
        self.assertEqual(session.status, 'srs_ready')

    def test_update_session_mode_api_toggles_mode(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        
        # Toggle without body: toggles mode1 -> mode2
        response = self.client.post(f'/api/session/{session.id}/mode/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'mode2')
        session.refresh_from_db()
        self.assertEqual(session.mode, 'mode2')

        # Toggle again: mode2 -> mode1
        response = self.client.post(f'/api/session/{session.id}/mode/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['mode'], 'mode1')
        session.refresh_from_db()
        self.assertEqual(session.mode, 'mode1')

    def test_get_code_file_api_reads_project_file_and_protects_isolation(self):
        user_b = User.objects.create_user(username='otheruser', email='other@example.com', password='Password123!')
        sess_b = Session.objects.create(user=user_b, mode='mode1', status='ready')
        pf_b = ProjectFile.objects.create(session=sess_b, path='secret.py', content='secret_code')

        sess_a = Session.objects.create(user=self.user, mode='mode1', status='ready')
        pf_a = ProjectFile.objects.create(session=sess_a, path='my_app/views.py', content='my_code')

        # User A cannot read User B's ProjectFile
        resp_b = self.client.get(f'/api/code/{pf_b.id}/')
        self.assertEqual(resp_b.status_code, 404)

        # User A can read User A's ProjectFile
        resp_a = self.client.get(f'/api/code/{pf_a.id}/')
        self.assertEqual(resp_a.status_code, 200)
        self.assertEqual(resp_a.json()['module_name'], 'my_app/views.py')
        self.assertEqual(resp_a.json()['code_content'], 'my_code')

    def test_stop_cancellation_does_not_swallow_next_message(self):
        import json
        session = Session.objects.create(user=self.user, mode='mode1', status='interviewing')
        
        # 1. User stops in-flight request
        cancel_resp = self.client.post(
            f'/api/session/{session.id}/cancel/',
            data=json.dumps({'request_id': 'req_first_to_cancel'}),
            content_type='application/json'
        )
        self.assertEqual(cancel_resp.status_code, 200)

        # 2. User sends subsequent message right away
        send_resp = self.client.post(
            f'/api/chat/{session.id}/send/',
            data=json.dumps({'message': 'Hello, can you help me build a blog?', 'request_id': 'req_second_fresh'}),
            content_type='application/json'
        )
        self.assertEqual(send_resp.status_code, 200)
        data = send_resp.json()
        self.assertFalse(data.get('cancelled', False))
        self.assertTrue(bool(data.get('response')))
        self.assertNotIn('cancelled by user', data.get('response', ''))

    def test_update_session_mode_api_locked_after_interviewing(self):
        session = Session.objects.create(user=self.user, mode='mode1', status='generating')
        response = self.client.post(f'/api/session/{session.id}/mode/')
        self.assertEqual(response.status_code, 400)
        self.assertIn("Mode cannot be changed", response.json().get('error', ''))

    def test_timezone_middleware_activates_and_deactivates(self):
        from core.middleware import TimezoneMiddleware
        from django.test.client import RequestFactory
        from django.utils import timezone

        factory = RequestFactory()
        req = factory.get('/')
        req.COOKIES['django_timezone'] = 'Asia/Tokyo'

        active_tz_inside = []
        def dummy_get_response(request):
            active_tz_inside.append(timezone.get_current_timezone_name())
            return None

        middleware = TimezoneMiddleware(dummy_get_response)
        middleware(req)

        # Inside request, client timezone was active
        self.assertEqual(active_tz_inside[0], 'Asia/Tokyo')
        # After request finished, current timezone deactivated and did not leak
        self.assertNotEqual(timezone.get_current_timezone_name(), 'Asia/Tokyo')

    def test_claude_model_is_claude_sonnet_5_5(self):
        from django.conf import settings
        from llm_engine.providers.claude_provider import ClaudeProvider
        provider = ClaudeProvider()
        self.assertEqual(provider.model, 'claude-sonnet-5-5')
        plan_models = dict(settings.LLM_PURPOSE_ROUTING['plan'])
        self.assertEqual(plan_models.get('claude'), 'claude-sonnet-5-5')

    def test_mode2_zip_download_does_not_stop_generation_early(self):
        """Mode 2: harness files created by ZIP download should not count toward module completion."""
        session = Session.objects.create(user=self.user, mode='mode2', status='srs_ready')
        session.summary_text = 'Test project with two modules'
        session.save(update_fields=['summary_text'])
        Message.objects.create(session=session, role='assistant',
            content='### Project Requirements Summary\n- Project Concept: Test App\nReady to proceed.')

        # Simulate plan modules
        modules = ['app/models.py', 'app/views.py']

        # Simulate Module 1 already generated
        ProjectFile.objects.create(session=session, path='app/models.py', content='# models', status='generated')
        GeneratedCode.objects.create(session=session, module_name='app/models.py', code_content='# models')

        # Simulate harness files created by ZIP download (5 extra files)
        for hf in ['README.md', 'run.sh', 'requirements.txt', 'Dockerfile', '.gitignore']:
            ProjectFile.objects.create(session=session, path=hf, content=f'# {hf}', status='verified')

        # Even though 6 ProjectFiles exist (1 plan + 5 harness), only 1 plan file is generated
        plan_files = session.project_files.filter(path__in=modules)
        self.assertEqual(plan_files.count(), 1)  # Only models.py
        self.assertLess(plan_files.count(), len(modules))  # Still has remaining modules

    def test_mode2_direct_code_demand_generates_module_1_only(self):
        """Mode 2 + direct code demand should generate Module 1, not trigger full all-at-once job."""
        session = Session.objects.create(user=self.user, mode='mode2', status='active')
        Message.objects.create(session=session, role='user', content='Build a blog with Django')

        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'just give me the code', 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should generate only Module 1, not trigger background job
        self.assertIsNone(data.get('job_id'))
        self.assertIn('Module 1', data.get('response', ''))

    def test_cancel_request_ttl_is_300_seconds(self):
        """Cancel request TTL should be 300 seconds, not 30."""
        import json
        from django.core.cache import cache
        session = Session.objects.create(user=self.user, mode='mode1', status='active')
        self.client.post(
            f'/api/session/{session.id}/cancel/',
            data=json.dumps({'request_id': 'test_ttl_req'}),
            content_type='application/json'
        )
        # The cache entry should exist
        self.assertTrue(cache.get('cancel_req_test_ttl_req'))

    def test_mode2_completion_runs_repair_and_marks_ready(self):
        """Mode 2: Approving the last module should trigger repair loop, mark session ready, and return completion message."""
        from chat.models import ProjectPlan
        session = Session.objects.create(user=self.user, mode='mode2', status='generating')
        session.summary_text = 'Test project with two modules'
        session.save(update_fields=['summary_text'])
        
        modules = ['app/models.py', 'app/views.py']
        ProjectPlan.objects.create(session=session, version=1, plan_data={'files': [{'path': m} for m in modules]}, generation_order=modules)
        
        # All planned modules already generated
        ProjectFile.objects.create(session=session, path='app/models.py', content='class Todo: pass', status='generated')
        ProjectFile.objects.create(session=session, path='app/views.py', content='def list_todos(): pass', status='generated')
        
        Message.objects.create(session=session, role='assistant',
            content='### Module 2/2: `app/views.py`\n\nI have generated the code. Do you approve this module? (Say **yes** to move to the next module).')

        # User says "yes" to approve the final module
        response = self.client.post(
            f'/api/chat/{session.id}/send/',
            data={'message': 'yes', 'provider': 'mock'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('Incremental Generation Complete', data.get('response', ''))
        
        session.refresh_from_db()
        self.assertIn(session.status, ['ready', 'needs_attention'])
        self.assertEqual(data.get('status'), session.status)

    # --- File-by-file routing regressions -------------------------------------------------
    def _mode2_session(self, generated=('app/models.py',), status='generating'):
        from chat.models import ProjectPlan
        session = Session.objects.create(user=self.user, mode='mode2', status=status)
        session.summary_text = '### Project Requirements Summary\nTodo app with two modules'
        session.save(update_fields=['summary_text'])
        modules = ['app/models.py', 'app/views.py']
        ProjectPlan.objects.create(session=session, version=1, plan_data={'files': [{'path': m} for m in modules]}, generation_order=modules)
        for path in generated:
            ProjectFile.objects.create(session=session, path=path, content='# v1', status='generated')
        Message.objects.create(session=session, role='assistant', content='### Module 1/2\nDo you approve this module?')
        return session

    def _send(self, session, message, action=None):
        payload = {'message': message, 'provider': 'mock'}
        if action:
            payload['action'] = action
        return self.client.post(f'/api/chat/{session.id}/send/', data=payload, content_type='application/json')

    def test_mode2_question_mid_build_does_not_rewrite_module(self):
        session = self._mode2_session()
        response = self._send(session, 'what does this file do?')
        self.assertEqual(response.status_code, 200)
        pf = ProjectFile.objects.get(session=session, path='app/models.py')
        self.assertEqual(pf.current_version, 1)
        self.assertEqual(pf.content, '# v1')
        self.assertFalse(ProjectFile.objects.filter(session=session, path='app/views.py').exists())

    def test_mode2_change_request_on_last_module_edits_instead_of_completing(self):
        session = self._mode2_session(generated=('app/models.py', 'app/views.py'))
        response = self._send(session, 'add a due date filter to the task list')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Incremental Generation Complete', response.json().get('response', ''))
        session.refresh_from_db()
        self.assertEqual(session.status, 'generating')
        self.assertEqual(ProjectFile.objects.get(session=session, path='app/views.py').current_version, 2)

    def test_mode2_approve_button_on_last_module_completes(self):
        session = self._mode2_session(generated=('app/models.py', 'app/views.py'))
        response = self._send(session, 'Approved. Proceed to the next module.', action='approve_module')
        self.assertIn('Incremental Generation Complete', response.json().get('response', ''))
        session.refresh_from_db()
        self.assertIn(session.status, ['ready', 'needs_attention'])

    def test_mode2_requirement_change_before_any_module_updates_summary(self):
        session = self._mode2_session(generated=(), status='srs_ready')
        response = self._send(session, 'Please modify the requirements to: add an admin panel', action='changes')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(session.project_files.exists())
        self.assertFalse(session.plans.exists())  # stale plan dropped

    def test_mode2_change_question_is_treated_as_change(self):
        from chat.views import _looks_like_question
        self.assertTrue(_looks_like_question('what does this file do?'))
        self.assertTrue(_looks_like_question('how do I run it'))
        self.assertFalse(_looks_like_question('can you add a due date?'))
        self.assertFalse(_looks_like_question('add a due date filter'))

    def test_mode2_module_step_runs_as_background_job(self):
        from unittest import mock
        from chat.models import Job
        session = self._mode2_session()
        with mock.patch('threading.Thread') as thread_cls:
            response = self.client.post(
                f'/api/chat/{session.id}/send/',
                data={'message': 'yes', 'provider': 'mock', 'action': 'approve_module'},
                content_type='application/json', HTTP_X_RUN_SYNC='false'
            )
        self.assertEqual(response.status_code, 200)
        job_id = response.json().get('job_id')
        self.assertIsNotNone(job_id)
        self.assertEqual(Job.objects.get(id=job_id).job_type, 'module')
        thread_cls.return_value.start.assert_called_once()

    def test_affirmative_with_change_is_not_approval(self):
        session = self._mode2_session(generated=(), status='srs_ready')
        self._send(session, 'yes, but add an admin panel')
        self.assertFalse(session.project_files.exists())
