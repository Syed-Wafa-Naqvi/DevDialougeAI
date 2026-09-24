from django.test import TestCase, Client
from django.contrib.auth.models import User
from accounts.models import Profile

class AccountsTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def test_signup_and_otp_generation(self):
        response = self.client.post('/signup/', {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'Password123!',
            'confirm_password': 'Password123!',
            'plan': 'basic'
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.filter(username='newuser').first()
        self.assertIsNotNone(user)
        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.profile.otp)

    def test_login_flow(self):
        user = User.objects.create_user(username='activeuser', email='active@example.com', password='Password123!')
        user.is_active = True
        user.save()
        user.profile.is_verified = True
        user.profile.save()

        response = self.client.post('/login/', {
            'username': 'activeuser',
            'password': 'Password123!'
        })
        self.assertEqual(response.status_code, 302)
