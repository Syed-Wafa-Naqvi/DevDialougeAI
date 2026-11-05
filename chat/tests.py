from django.test import TestCase, Client
from django.contrib.auth.models import User
from accounts.models import Profile
from chat.models import Session, Message, GeneratedCode

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
