import io
import re
import zipfile
from chat.models import GeneratedCode, ProjectFile, VerificationRun
from generator.path_safety import PathSafetyManager
from exporter.harness_agent import AIHarnessPackager

class ZipArchiver:
    @classmethod
    def get_project_name(cls, session) -> str:
        """
        Resolves the true project name from project plans, SRS summaries, or conversation context,
        avoiding generic fallback titles like 'IDont Know What To'.
        """
        # 1. Check if session has a structured ProjectPlan with a valid project_name
        plan = session.plans.first()
        if plan and isinstance(plan.plan_data, dict):
            pname = plan.plan_data.get('project_name')
            if pname and pname.strip() and pname.lower() not in ['mock_app', 'new chat', 'untitled']:
                clean_pname = re.sub(r'[^\w\s-]', '', pname).strip().replace(' ', '_')
                if clean_pname:
                    return clean_pname

        generic_phrases = {
            'new chat', 'idont know what to', 'i dont know what to', "i don't know what to",
            'hey', 'hello', 'what', 'what the heck is this', 'explain this error',
            'project', 'untitled', 'test app'
        }

        # 2. Check conversation history for user-specified project domain/concept
        messages = list(session.messages.order_by('id'))
        for msg in messages:
            if msg.role == 'user':
                text = msg.content.strip()
                lower = text.lower()
                domain_matches = [
                    'collaboration tool', 'collaboration', 'ecommerce', 'todo', 'blog', 
                    'chat app', 'social media', 'crm', 'inventory', 'marketplace', 
                    'booking', 'dashboard', 'real-time'
                ]
                if any(k in lower for k in domain_matches) and len(text) <= 50:
                    clean = re.sub(r'[^\w\s-]', '', text).strip()
                    if clean:
                        if session.title.lower() in generic_phrases:
                            session.title = clean.title()
                            session.save(update_fields=['title'])
                        return clean.replace(' ', '_')

        # 3. Check for Project Concept in SRS summary messages
        for msg in reversed(messages):
            if "project concept" in msg.content.lower():
                for line in msg.content.splitlines():
                    if "project concept" in line.lower() and ":" in line:
                        concept = line.split(":", 1)[-1].strip().strip("*# ")
                        clean_concept = re.sub(r'[^\w\s-]', '', concept).strip()
                        if clean_concept and len(clean_concept) <= 50:
                            if session.title.lower() in generic_phrases:
                                session.title = clean_concept.title()
                                session.save(update_fields=['title'])
                            return clean_concept.replace(' ', '_')

        # 4. Use session title if specific
        clean_title = session.title.strip()
        if clean_title and clean_title.lower() not in generic_phrases and not clean_title.endswith('?'):
            clean = re.sub(r'[^\w\s-]', '', clean_title).strip().replace(' ', '_')
            if clean:
                return clean

        return "Project"

    @classmethod
    def create_project_zip(cls, session) -> bytes:
        """
        Builds the complete project ZIP archive.
        Uses the dynamic AIHarnessPackager agent to analyze the generated files
        and automatically generate missing build manifests, entrypoints, and 1-click runners
        for ANY programming language (Node.js, Go, Rust, Python, Java, etc.).
        """
        buffer = io.BytesIO()
        codes = list(GeneratedCode.objects.filter(session=session))
        project_files = list(ProjectFile.objects.filter(session=session))
        project_name = cls.get_project_name(session)
        display_title = project_name.replace('_', ' ')

        # 1. Collect all existing project and generated code files
        existing_files = {}
        for pf in project_files:
            try:
                safe_path = PathSafetyManager.validate_path(pf.path)
                existing_files[safe_path] = pf.content
            except Exception:
                pass

        for code_obj in codes:
            try:
                safe_path = PathSafetyManager.validate_path(code_obj.module_name)
                if safe_path not in existing_files:
                    existing_files[safe_path] = code_obj.code_content
            except Exception:
                pass

        # 2. Invoke AI Harness Packager Agent to generate dynamic runner, build, and manifest files
        harness_files = AIHarnessPackager.generate_harness(session, existing_files, project_name)

        # Merge files
        final_files = {**existing_files, **harness_files}

        # 3. Assemble the in-memory ZIP archive
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path, content in final_files.items():
                try:
                    safe_path = PathSafetyManager.validate_path(file_path)
                    content_str = content if isinstance(content, str) else str(content)
                    
                    # Grant executable permissions to shell and python runners on Unix/macOS
                    if safe_path in ('run.sh', 'run.py', 'manage.py') or safe_path.endswith(('.sh', '.command')):
                        info = zipfile.ZipInfo(safe_path)
                        info.external_attr = 0o755 << 16
                        zf.writestr(info, content_str)
                    else:
                        zf.writestr(safe_path, content_str)
                except Exception:
                    pass

            # 4. Include VERIFICATION.md if verification records exist
            latest_verif = VerificationRun.objects.filter(session=session).order_by('-created_at').first()
            if latest_verif:
                status_str = "PASSED" if latest_verif.passed else "ISSUES DETECTED"
                if latest_verif.issues:
                    issue_lines = [
                        f"- [{i.get('severity', 'error').upper()}] {i.get('file')}:{i.get('line')} ({i.get('check')}): {i.get('message')}"
                        for i in latest_verif.issues
                    ]
                    issues_section = "## Issues Summary:\n" + "\n".join(issue_lines)
                else:
                    issues_section = "No verification issues detected."

                verif_content = (
                    f"# Verification Report - {display_title}\n\n"
                    f"- **Verification Level**: {latest_verif.level.upper()}\n"
                    f"- **Status**: {status_str}\n"
                    f"- **Errors**: {latest_verif.error_count}\n"
                    f"- **Warnings**: {latest_verif.warning_count}\n"
                    f"- **Timestamp**: {latest_verif.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                    f"{issues_section}\n"
                )
                zf.writestr("VERIFICATION.md", verif_content)

        buffer.seek(0)
        return buffer.getvalue()
