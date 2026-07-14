from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import Profile, Session, Message, GeneratedCode
from core.dialogue_engine import DialogueEngine

class ProfileModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', email='test@example.com', password='testpassword')

    def test_profile_automatic_creation(self):
        """Test that a Profile is automatically created when a User is created."""
        self.assertIsNotNone(self.user.profile)
        self.assertEqual(self.user.profile.plan, 'basic')
        self.assertFalse(self.user.profile.is_verified)

    def test_otp_generation_and_validation(self):
        """Test OTP generation, validation, and expiration logic."""
        profile = self.user.profile
        otp = profile.generate_otp()
        
        self.assertIsNotNone(otp)
        self.assertEqual(len(otp), 6)
        self.assertTrue(profile.is_otp_valid(otp))
        
        # Test wrong OTP
        self.assertFalse(profile.is_otp_valid("000000"))
        
        # Test expired OTP (set time back 3 minutes)
        profile.otp_created_at = timezone.now() - timezone.timedelta(minutes=3)
        profile.save()
        self.assertFalse(profile.is_otp_valid(otp))

class DialogueEngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser2', email='test2@example.com', password='testpassword')
        self.user.profile.is_verified = True
        self.user.profile.save()
        self.session = Session.objects.create(user=self.user, mode='mode1')

    def test_dialogue_flow(self):
        """Test that the dialogue engine processes messages sequentially and asks correct questions."""
        # Initial description is created when creating session (typically)
        # Message 1: Initial prompt
        Message.objects.create(session=self.session, role='user', content="Build a task tracker app.")
        # Message 2: First question asked by views
        Message.objects.create(session=self.session, role='assistant', content=DialogueEngine.QUESTIONS[0][1])
        
        # Now submit user response 1 (tech stack)
        resp1 = DialogueEngine.process_message(self.session, "Django and SQLite")
        self.assertIn(DialogueEngine.QUESTIONS[1][1], resp1)
        
        # Submit user response 2 (features)
        resp2 = DialogueEngine.process_message(self.session, "Task creation, due dates, project views")
        self.assertIn(DialogueEngine.QUESTIONS[2][1], resp2)
        
        # Submit user response 3 (auth)
        resp3 = DialogueEngine.process_message(self.session, "Simple login and signup with passwords")
        self.assertIn(DialogueEngine.QUESTIONS[3][1], resp3)
        
        # Submit user response 4 (constraints)
        resp4 = DialogueEngine.process_message(self.session, "None")
        self.assertIn("Project Requirements Summary", resp4)
        
        # Submit confirmation
        resp5 = DialogueEngine.process_message(self.session, "Yes, please generate the code")
        self.assertIn("Codebase Generated Successfully!", resp5)
        self.assertEqual(self.session.generated_codes.count(), 3)
        
        # Retrieve code content checks
        modules = [c.module_name for c in self.session.generated_codes.all()]
        self.assertIn("models.py", modules)
        self.assertIn("views.py", modules)
        self.assertIn("templates/index.html", modules)
