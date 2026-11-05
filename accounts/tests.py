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

    def test_cache_based_rate_limiting_persists_across_cleared_cookies(self):
        from django.core.cache import cache
        cache.clear()

        # Trigger failed logins up to limit (10 attempts)
        for _ in range(10):
            self.client.post('/login/', {'username': 'ratelimituser', 'password': 'wrongpassword'})

        # 11th attempt should be blocked by rate limit
        response = self.client.post('/login/', {'username': 'ratelimituser', 'password': 'wrongpassword'})
        self.assertContains(response, "Too many login attempts")

        # Clear client session cookies to simulate cookie deletion
        self.client.cookies.clear()

        # Attempt with cleared cookie should STILL be rate limited
        response_cleared = self.client.post('/login/', {'username': 'ratelimituser', 'password': 'wrongpassword'})
        self.assertContains(response_cleared, "Too many login attempts")

    def test_forgot_password_nonexistent_email_does_not_bounce(self):
        # Request reset for an unknown email
        response = self.client.post('/forgot-password/', {'email': 'unknown@example.com'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/reset-password/')

        # Follow redirect - should render the reset page with form, not bounce back to forgot_password
        follow_response = self.client.get('/reset-password/')
        self.assertEqual(follow_response.status_code, 200)

        # Submitting an OTP for nonexistent email returns standard invalid OTP error without account enumeration
        post_response = self.client.post('/reset-password/', {
            'otp': '123456',
            'new_password': 'NewPassword123!',
            'confirm_new_password': 'NewPassword123!'
        })
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Invalid or expired OTP")
