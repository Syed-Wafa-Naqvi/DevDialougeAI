from django.db import models
from django.conf import settings

class LLMCallLog(models.Model):
    PURPOSE_CHOICES = [
        ('chat', 'Chat / Elicitation'),
        ('completeness', 'Completeness Score'),
        ('srs', 'SRS Synthesis'),
        ('plan', 'Architecture Plan'),
        ('codegen', 'Code Generation'),
        ('repair', 'Code Repair'),
        ('summary', 'Conversation Summary'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='llm_call_logs'
    )
    session = models.ForeignKey(
        'chat.Session',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='llm_call_logs'
    )
    purpose = models.CharField(max_length=50, choices=PURPOSE_CHOICES, default='chat')
    provider = models.CharField(max_length=50)
    model_id = models.CharField(max_length=100, default='default')
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    is_token_estimated = models.BooleanField(default=True)
    latency_ms = models.IntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=6, default=0.0)
    success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, default='')
    fallback_used = models.BooleanField(default=False)
    prompt_body = models.TextField(blank=True, null=True)
    response_body = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.purpose}] {self.provider}/{self.model_id} - {'OK' if self.success else 'FAIL'} ({self.latency_ms}ms)"
