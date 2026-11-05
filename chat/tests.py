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
        self.assertTrue(session.generated_codes.exists())
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
        self.assertTrue(session.generated_codes.exists())

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
