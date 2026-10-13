import time
from chat.models import Job, JobEvent, Session, ProjectFile
from chat.state_machine import SessionStateMachine
from generator.planner import PlanGenerator
from generator.code_builder import CodeBuilder
from generator.repair import CodeRepairEngine
from generator.verifier import StaticVerifier

class JobConcurrencyError(ValueError):
    """Raised when a job is created while another job is active for the same session."""
    pass

class JobExecutionEngine:
    @classmethod
    def create_job(cls, session, user, job_type: str) -> Job:
        """
        Creates a new Job instance after verifying no active job exists for the session.
        Raises JobConcurrencyError if a job is already queued or running.
        """
        active_jobs = session.jobs.filter(status__in=['queued', 'running'])
        if active_jobs.exists():
            raise JobConcurrencyError("A job is already actively running or queued for this session.")

        from django.conf import settings
        max_user_jobs = getattr(settings, 'MAX_CONCURRENT_JOBS_PER_USER', 2)
        if user and getattr(user, 'is_authenticated', False):
            user_active = Job.objects.filter(user=user, status__in=['queued', 'running']).count()
            if user_active >= max_user_jobs:
                raise JobConcurrencyError(f"User has reached the maximum allowed concurrent background jobs ({max_user_jobs}).")

        return Job.objects.create(
            session=session,
            user=user,
            job_type=job_type,
            status='queued',
            progress_current=0,
            progress_total=100
        )


    @classmethod
    def run_job(cls, job_id: int, provider_name: str = None) -> Job:
        """
        Executes the job pipeline based on job_type.
        Supports clean cancellation checks between execution phases.
        """
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            raise ValueError(f"Job #{job_id} not found.")

        job.status = 'running'
        job.save(update_fields=['status'])
        job.log_event('info', f"Started background job #{job.id} [{job.job_type}].")

        try:
            if job.job_type == 'plan':
                cls._execute_plan_job(job, provider_name)
            elif job.job_type in ('generate', 'repair', 'feedback_edit'):
                cls._execute_generation_job(job, provider_name)
            else:
                job.status = 'succeeded'
                job.save(update_fields=['status'])
        except Exception as e:
            job.status = 'failed'
            job.error_message = str(e)
            job.save(update_fields=['status', 'error_message'])
            job.log_event('error', f"Job execution failed: {str(e)}")

        return job

    @classmethod
    def _execute_plan_job(cls, job: Job, provider_name: str = None):
        session = job.session
        SessionStateMachine.transition_to(session, 'plan_draft')

        job.progress_current = 20
        job.save(update_fields=['progress_current'])
        job.log_event('info', "Generating architecture plan contract...")

        # Fetch latest SRS summary from messages
        srs_msgs = session.messages.filter(role='assistant', content__contains="Project Requirements Summary")
        srs_summary = srs_msgs.last().content if srs_msgs.exists() else "Standard web application"

        # Check cancellation
        job.refresh_from_db()
        if job.cancel_requested:
            job.status = 'cancelled'
            job.save(update_fields=['status'])
            job.log_event('info', "Job cancelled by user.")
            return

        plan_obj = PlanGenerator.generate_plan(srs_summary, session, provider_name=provider_name)
        job.progress_current = 100
        job.status = 'succeeded'
        job.result_summary = f"Plan v{plan_obj.version} generated successfully with {len(plan_obj.generation_order)} target files."
        job.save(update_fields=['progress_current', 'status', 'result_summary'])

        job.log_event('info', f"Architecture plan v{plan_obj.version} created.", data=plan_obj.plan_data)

    @classmethod
    def _execute_generation_job(cls, job: Job, provider_name: str = None):
        session = job.session
        SessionStateMachine.transition_to(session, 'generating')

        # Collect current workspace files
        existing_files = {pf.path: pf.content for pf in session.project_files.all()}

        # Fetch latest plan
        plan_obj = session.plans.filter(status__in=['approved', 'draft']).first()
        plan_data = plan_obj.plan_data if plan_obj else None
        gen_order = plan_obj.generation_order if plan_obj else []

        if not gen_order and existing_files:
            gen_order = list(existing_files.keys())

        if not gen_order:
            gen_order = ["todo/models.py", "todo/views.py"]

        total_files = len(gen_order)
        job.progress_total = total_files * 10
        job.save(update_fields=['progress_total'])

        generated_files = dict(existing_files)

        for idx, file_path in enumerate(gen_order):
            # Check cancellation between files
            job.refresh_from_db()
            if job.cancel_requested:
                job.status = 'cancelled'
                job.save(update_fields=['status'])
                job.log_event('info', f"Job cancelled by user while writing '{file_path}'.")
                return

            job.log_event('file_started', f"Writing file ({idx+1}/{total_files}): '{file_path}'...")
            
            # Generate code module
            code_content = CodeBuilder.generate_code_for_module(file_path, "Generate module", provider_name=provider_name)
            generated_files[file_path] = code_content

            # Save / version ProjectFile
            pf, created = ProjectFile.objects.get_or_create(
                session=session,
                path=file_path,
                defaults={'content': code_content, 'status': 'generated', 'current_version': 1}
            )
            if not created:
                pf.create_new_version(code_content, source='generate')

            job.progress_current = (idx + 1) * 10
            job.save(update_fields=['progress_current'])
            job.log_event('file_done', f"Completed '{file_path}'.")

        # Static Verification & Repair Loop Phase
        SessionStateMachine.transition_to(session, 'verifying')
        job.log_event('info', "Running static verification and repair loop...")

        repair_res = CodeRepairEngine.run_repair_loop(
            session=session,
            files_dict=generated_files,
            plan_data=plan_data,
            max_attempts=3,
            provider_name=provider_name
        )

        final_status = repair_res['status']
        if final_status in ('verified', 'verified_with_warnings'):
            SessionStateMachine.transition_to(session, 'ready')
        else:
            SessionStateMachine.transition_to(session, 'needs_attention')

        job.status = 'succeeded'
        job.progress_current = job.progress_total
        job.result_summary = repair_res['honest_message']
        job.save(update_fields=['status', 'progress_current', 'result_summary'])

        job.log_event('verify_result', repair_res['honest_message'], data=repair_res['verification'])
