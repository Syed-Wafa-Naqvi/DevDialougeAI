from django.db import models
from django.contrib.auth.models import User

class Session(models.Model):
    MODE_CHOICES = [
        ('mode1', 'Mode 1: Dialogue-Driven'),
        ('mode2', 'Mode 2: Incremental'),
    ]
    STATUS_CHOICES = [
        ('interviewing', 'Requirement Elicitation'),
        ('srs_ready', 'SRS Synthesized'),
        ('plan_draft', 'Plan Draft'),
        ('plan_approved', 'Plan Approved'),
        ('generating', 'Generating Code'),
        ('verifying', 'Verifying Codebase'),
        ('repairing', 'Repairing Codebase'),
        ('awaiting_review', 'Awaiting Review'),
        ('applying_feedback', 'Applying Feedback'),
        ('ready', 'Verified & Ready'),
        ('needs_attention', 'Needs Attention'),
        ('active', 'Active'),
        ('completed', 'Completed'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='mode1')
    started_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='interviewing')
    title = models.CharField(max_length=255, default="New Chat")
    has_custom_title = models.BooleanField(default=False)
    summary_text = models.TextField(blank=True, default='')

    def __str__(self):
        return f"Session {self.id} ({self.get_mode_display()}) - {self.user.username}"


class ProjectPlan(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('superseded', 'Superseded'),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='plans')
    plan_data = models.JSONField(default=dict)
    generation_order = models.JSONField(default=list)
    version = models.IntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']

    def __str__(self):
        return f"Plan v{self.version} for Session {self.session.id} [{self.status}]"



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


class ProjectFile(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('generated', 'Generated'),
        ('verified', 'Verified'),
        ('has_issues', 'Has Issues'),
        ('awaiting_review', 'Awaiting Review'),
        ('approved', 'Approved'),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='project_files')
    path = models.CharField(max_length=255)
    content = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    current_version = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'path')
        ordering = ['path']

    def __str__(self):
        return f"{self.path} (v{self.current_version}) [{self.status}]"

    def create_new_version(self, content: str, source: str = 'generate') -> 'FileVersion':
        """Creates a new version record for this file and updates current content/version."""
        self.current_version += 1
        self.content = content
        self.save()

        return FileVersion.objects.create(
            project_file=self,
            version_number=self.current_version,
            content=content,
            source=source
        )


class FileVersion(models.Model):
    SOURCE_CHOICES = [
        ('generate', 'Initial Generation'),
        ('repair', 'Automated Repair'),
        ('user_feedback', 'User Feedback'),
        ('manual', 'Manual Edit'),
    ]

    project_file = models.ForeignKey(ProjectFile, on_delete=models.CASCADE, related_name='versions')
    version_number = models.IntegerField()
    content = models.TextField()
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='generate')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('project_file', 'version_number')
        ordering = ['version_number']

    def __str__(self):
        return f"{self.project_file.path} v{self.version_number} ({self.source})"


class VerificationRun(models.Model):
    LEVEL_CHOICES = [
        ('static', 'Static Analysis'),
        ('runtime', 'Runtime Verification'),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='verification_runs')
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='static')
    passed = models.BooleanField(default=False)
    error_count = models.IntegerField(default=0)
    warning_count = models.IntegerField(default=0)
    issues = models.JSONField(default=list)
    duration_ms = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Verification ({self.level}) for Session {self.session.id}: {'PASSED' if self.passed else 'FAILED'} ({self.error_count} errs, {self.warning_count} warns)"


class Job(models.Model):
    JOB_TYPE_CHOICES = [
        ('plan', 'Architecture Plan'),
        ('generate', 'Code Generation'),
        ('verify', 'Static Verification'),
        ('repair', 'Code Repair'),
        ('feedback_edit', 'Feedback Edit'),
    ]

    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('succeeded', 'Succeeded'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name='jobs')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs')
    job_type = models.CharField(max_length=20, choices=JOB_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    progress_current = models.IntegerField(default=0)
    progress_total = models.IntegerField(default=100)
    result_summary = models.TextField(blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    cancel_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Job #{self.id} [{self.job_type}] in Session {self.session.id} ({self.status})"

    def log_event(self, kind: str, message: str, data: dict = None) -> 'JobEvent':
        """Logs a new sequential progress event for this job."""
        next_seq = (self.events.aggregate(models.Max('sequence_number'))['sequence_number__max'] or 0) + 1
        return JobEvent.objects.create(
            job=self,
            sequence_number=next_seq,
            kind=kind,
            message=message,
            data=data or {}
        )


class JobEvent(models.Model):
    KIND_CHOICES = [
        ('info', 'Information'),
        ('file_started', 'File Generation Started'),
        ('file_done', 'File Generation Completed'),
        ('verify_result', 'Verification Result'),
        ('repair_attempt', 'Repair Attempt'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ]

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='events')
    sequence_number = models.IntegerField()
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='info')
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('job', 'sequence_number')
        ordering = ['sequence_number']

    def __str__(self):
        return f"Job #{self.job.id} Event #{self.sequence_number} [{self.kind}]: {self.message}"



