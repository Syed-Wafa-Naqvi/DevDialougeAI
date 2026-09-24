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
