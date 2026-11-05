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

    def test_forgot_password_duplicate_email_no_crash(self):
        # Two users sharing same email should not crash with MultipleObjectsReturned 500
        User.objects.create_user(username='user1', email='duplicate@example.com', password='Password123!')
        User.objects.create_user(username='user2', email='duplicate@example.com', password='Password123!')
        response = self.client.post('/forgot-password/', {'email': 'duplicate@example.com'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/reset-password/')

    def test_unverified_user_login_sends_otp(self):
        user = User.objects.create_user(username='unverified', email='unverified@example.com', password='Password123!')
        user.is_active = False
        user.save()
        user.profile.is_verified = False
        user.profile.save()

        response = self.client.post('/login/', {
            'username': 'unverified',
            'password': 'Password123!'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/verify-otp/', response.url)
        user.profile.refresh_from_db()
        self.assertIsNotNone(user.profile.otp)

    def test_otp_generation_resets_failed_attempts(self):
        user = User.objects.create_user(username='otptest', email='otp@example.com', password='Password123!')
        profile = user.profile
        profile.otp_failed_attempts = 4
        profile.save()
        otp = profile.generate_otp()
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())
        self.assertEqual(profile.otp_failed_attempts, 0)
