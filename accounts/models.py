import base64
import hashlib
import hmac
import random
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.conf import settings

def get_field_encryption_key():
    raw_key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None) or settings.SECRET_KEY
    key_bytes = hashlib.sha256(raw_key.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(key_bytes)

def encrypt_api_key(raw_key: str) -> str:
    if not raw_key:
        return ""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(get_field_encryption_key())
        return f.encrypt(raw_key.encode('utf-8')).decode('utf-8')
    except Exception:
        key_bytes = get_field_encryption_key()
        xor_bytes = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(raw_key.encode('utf-8'))])
        return base64.b64encode(xor_bytes).decode('utf-8')

def decrypt_api_key(encrypted_key: str) -> str:
    if not encrypted_key:
        return ""
    try:
        from cryptography.fernet import Fernet
        f = Fernet(get_field_encryption_key())
        return f.decrypt(encrypted_key.encode('utf-8')).decode('utf-8')
    except Exception:
        key_bytes = get_field_encryption_key()
        raw_bytes = base64.b64decode(encrypted_key.encode('utf-8'))
        unxored = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(raw_bytes)])
        return unxored.decode('utf-8')

def mask_api_key(raw_key: str) -> str:
    if not raw_key:
        return ""
    if len(raw_key) <= 4:
        return "••••"
    return "••••••••" + raw_key[-4:]


class Profile(models.Model):
    PLAN_CHOICES = [
        ('basic', 'Basic'),
        ('pro', 'Pro'),
        ('premium', 'Premium'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, default='basic')
    is_verified = models.BooleanField(default=False)
    otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)
    otp_failed_attempts = models.IntegerField(default=0)
    otp_lockout_until = models.DateTimeField(blank=True, null=True)
    otp_last_resent_at = models.DateTimeField(blank=True, null=True)

    encrypted_openai_key = models.TextField(blank=True, default='')
    encrypted_gemini_key = models.TextField(blank=True, default='')

    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    def set_openai_key(self, raw_key: str):
        self.encrypted_openai_key = encrypt_api_key(raw_key)

    def get_openai_key(self) -> str:
        return decrypt_api_key(self.encrypted_openai_key)

    def get_masked_openai_key(self) -> str:
        return mask_api_key(self.get_openai_key())

    def set_gemini_key(self, raw_key: str):
        self.encrypted_gemini_key = encrypt_api_key(raw_key)

    def get_gemini_key(self) -> str:
        return decrypt_api_key(self.encrypted_gemini_key)

    def get_masked_gemini_key(self) -> str:
        return mask_api_key(self.get_gemini_key())

    def generate_otp(self):
        self.otp = f"{random.randint(100000, 999999)}"
        self.otp_created_at = timezone.now()
        self.otp_last_resent_at = timezone.now()
        self.save()
        return self.otp

    def can_resend_otp(self) -> tuple[bool, str]:
        if self.otp_last_resent_at:
            seconds_since = (timezone.now() - self.otp_last_resent_at).total_seconds()
            if seconds_since < 120:
                remaining = int(120 - seconds_since)
                return False, f"Please wait {remaining} seconds before requesting another OTP."
        return True, ""

    def is_otp_valid(self, user_otp: str) -> bool:
        valid, _ = self.verify_otp_with_reason(user_otp)
        return valid

    def verify_otp_with_reason(self, user_otp: str) -> tuple[bool, str]:
        now = timezone.now()
        if self.otp_lockout_until and now < self.otp_lockout_until:
            remaining_mins = int((self.otp_lockout_until - now).total_seconds() // 60) + 1
            return False, f"Too many failed verification attempts. Try again in {remaining_mins} minutes."

        if not self.otp or not self.otp_created_at:
            return False, "Invalid or expired OTP. Please try again."

        expiry_time = self.otp_created_at + timezone.timedelta(minutes=2)
        if now > expiry_time:
            return False, "OTP code has expired. Please request a new code."

        # Constant-time string comparison to prevent timing attacks
        match = hmac.compare_digest(str(self.otp), str(user_otp or ''))
        if match:
            self.otp_failed_attempts = 0
            self.otp_lockout_until = None
            self.save(update_fields=['otp_failed_attempts', 'otp_lockout_until'])
            return True, "Verification successful."
        else:
            self.otp_failed_attempts += 1
            if self.otp_failed_attempts >= 5:
                self.otp_lockout_until = now + timezone.timedelta(minutes=15)
            self.save(update_fields=['otp_failed_attempts', 'otp_lockout_until'])
            return False, "Invalid OTP code. Please try again."

    def __str__(self):
        return f"{self.user.username}'s Profile - {self.plan.upper()}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()

