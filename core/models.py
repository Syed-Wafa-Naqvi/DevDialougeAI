from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
import random

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
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)

    def generate_otp(self):
        self.otp = f"{random.randint(100000, 999999)}"
        self.otp_created_at = timezone.now()
        self.save()
        return self.otp

    def is_otp_valid(self, user_otp):
        if not self.otp or self.otp != user_otp:
            return False
        # OTP is valid for 2 minutes
        expiry_time = self.otp_created_at + timezone.timedelta(minutes=2)
        return timezone.now() <= expiry_time

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


class Session(models.Model):
    MODE_CHOICES = [
        ('mode1', 'Mode 1: Dialogue-Driven'),
        ('mode2', 'Mode 2: Incremental'),
    ]
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='mode1')
    started_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')
    title = models.CharField(max_length=255, default="New Chat")
    has_custom_title = models.BooleanField(default=False)

    def __str__(self):
        return f"Session {self.id} ({self.get_mode_display()}) - {self.user.username}"


class Message(models.Model):
    ROLE_CHOICES = [
        ('user', 'User'),
        ('assistant', 'Assistant'),
    ]
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.role.upper()} in Session {self.session.id} at {self.timestamp}"


class GeneratedCode(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='generated_codes')
    module_name = models.CharField(max_length=100)
    code_content = models.TextField()
    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.module_name} in Session {self.session.id}"
