from generator.verifier import StaticVerifier
from generator.runtime_verifier import RuntimeVerifier
from generator.protocol import EditProtocolEngine, ProtocolValidationError
from llm_engine.router import LLMRouter
from chat.models import VerificationRun, ProjectFile, FileVersion

class CodeRepairEngine:
    SYSTEM_PROMPT = (
        "You are an automated software repair engineer. Analyze the static verification error reports and project code.\n"
        "Your task is to produce precise JSON edit operations to fix ALL verification errors.\n"
        "Use replace_in_file operations whenever possible. Make sure replace_in_file.old matches existing text EXACTLY ONCE.\n"
        "Schema:\n"
        "{\n"
        '  "summary": "Brief explanation of repairs made",\n'
        '  "operations": [\n'
        '    {"op": "replace_in_file", "path": "todo/views.py", "old": "exact existing code", "new": "repaired code"}\n'
        '  ],\n'
        '  "notes_for_user": ["Optional notes"]\n'
        "}\n"
        "Return ONLY valid JSON."
    )

    @classmethod
    def run_repair_loop(cls, session, files_dict: dict, plan_data: dict = None, max_attempts: int = 3, provider_name: str = None) -> dict:
        """
        Executes the static verification and automated self-repair loop.
        Returns a dict: {'status': str, 'files': dict, 'attempts': int, 'verification': dict, 'honest_message': str}
        """
        current_files = dict(files_dict)
        attempts = 0
        user = getattr(session, 'user', None)

        # Initial Verification Run
        initial_verif = StaticVerifier.verify_project(current_files, plan_data=plan_data)
        cls._record_verification_run(session, initial_verif, level='static')

        runtime_res = None
        if initial_verif['error_count'] == 0:
            runtime_res = RuntimeVerifier.run_verification(current_files, user=user, plan_data=plan_data)
            if runtime_res.get('executed'):
                cls._record_verification_run(session, runtime_res, level='runtime')
                if not runtime_res['passed']:
                    initial_verif = runtime_res

        if initial_verif['error_count'] == 0:
            status = 'verified' if initial_verif['warning_count'] == 0 else 'verified_with_warnings'
            msg = cls._format_honest_message(len(current_files), attempts, initial_verif, status, runtime_res=runtime_res)
            return {
                'status': status,
                'files': current_files,
                'attempts': attempts,
                'verification': initial_verif,
                'honest_message': msg
            }

        prev_fingerprints = {i['fingerprint'] for i in initial_verif['issues'] if i['severity'] == 'error'}

        while attempts < max_attempts:
            attempts += 1
            failing_issues = [i for i in initial_verif['issues'] if i['severity'] == 'error']

            prompt = cls._build_repair_prompt(current_files, failing_issues, plan_data)

            raw_resp = LLMRouter.generate(
                prompt=prompt,
                system_prompt=cls.SYSTEM_PROMPT,
                provider_name=provider_name,
                purpose='repair',
                session=session
            )

            try:
                payload = EditProtocolEngine.parse_payload(raw_resp)
                validated_ops = EditProtocolEngine.validate_operations(payload, current_files)
                candidate_files = EditProtocolEngine.apply_operations_atomically(validated_ops, current_files)
            except ProtocolValidationError:
                # If model response failed validation, stop repair loop and return current state
                break

            # Re-verify candidate files
            candidate_verif = StaticVerifier.verify_project(candidate_files, plan_data=plan_data)
            candidate_fingerprints = {i['fingerprint'] for i in candidate_verif['issues'] if i['severity'] == 'error'}

            # Check termination rules:
            # 1. Regression Check: New errors introduced
            new_errors_introduced = candidate_fingerprints - prev_fingerprints
            if new_errors_introduced and candidate_verif['error_count'] >= initial_verif['error_count']:
                # Rollback attempt
                break

            # 2. No Progress Check: Error fingerprints set did not shrink
            if len(candidate_fingerprints) >= len(prev_fingerprints):
                # Rollback attempt
                break

            # Attempt succeeded in reducing errors! Apply changes to workspace
            current_files = candidate_files
            initial_verif = candidate_verif
            prev_fingerprints = candidate_fingerprints

            # Persist repaired file versions
            cls._persist_repaired_files(session, current_files, validated_ops)
            cls._record_verification_run(session, initial_verif, level='static')

            if initial_verif['error_count'] == 0:
                runtime_res = RuntimeVerifier.run_verification(current_files, user=user, plan_data=plan_data)
                if runtime_res.get('executed'):
                    cls._record_verification_run(session, runtime_res, level='runtime')
                    if not runtime_res['passed']:
                        initial_verif = runtime_res
                        prev_fingerprints = {i['fingerprint'] for i in initial_verif['issues'] if i['severity'] == 'error'}
                        continue

                status = 'verified' if initial_verif['warning_count'] == 0 else 'verified_with_warnings'
                msg = cls._format_honest_message(len(current_files), attempts, initial_verif, status, runtime_res=runtime_res)
                return {
                    'status': status,
                    'files': current_files,
                    'attempts': attempts,
                    'verification': initial_verif,
                    'honest_message': msg
                }

        # If loop finishes with remaining errors
        status = 'needs_attention'
        msg = cls._format_honest_message(len(current_files), attempts, initial_verif, status, runtime_res=runtime_res)
        return {
            'status': status,
            'files': current_files,
            'attempts': attempts,
            'verification': initial_verif,
            'honest_message': msg
        }

    @classmethod
    def _build_repair_prompt(cls, files: dict, issues: list, plan_data: dict) -> str:
        issue_lines = [f"- File '{i['file']}' Line {i['line']} [{i['check']}]: {i['message']}" for i in issues]
        issues_text = "\n".join(issue_lines)

        failing_files = {i['file'] for i in issues}
        file_snippets = []
        for path in failing_files:
            if path in files:
                file_snippets.append(f"=== File: {path} ===\n{files[path]}")

        snippets_text = "\n\n".join(file_snippets)

        return (
            f"VERIFICATION ISSUES TO REPAIR:\n{issues_text}\n\n"
            f"FAILING FILES CONTENT:\n{snippets_text}\n\n"
            "Generate atomic replace_in_file JSON operations to resolve these issues."
        )

    @classmethod
    def _record_verification_run(cls, session, verif_result: dict, level: str = 'static'):
        if not session:
            return
        try:
            VerificationRun.objects.create(
                session=session,
                level=level,
                passed=verif_result['passed'],
                error_count=verif_result['error_count'],
                warning_count=verif_result['warning_count'],
                issues=verif_result['issues'],
                duration_ms=0
            )
        except Exception:
            pass

    @classmethod
    def _persist_repaired_files(cls, session, current_files: dict, validated_ops: list):
        if not session:
            return
        modified_paths = {op['path'] for op in validated_ops}
        for path in modified_paths:
            if path in current_files:
                pf, created = ProjectFile.objects.get_or_create(
                    session=session,
                    path=path,
                    defaults={'content': current_files[path], 'status': 'verified', 'current_version': 1}
                )
                if not created:
                    pf.create_new_version(current_files[path], source='repair')

    @classmethod
    def _format_honest_message(cls, file_count: int, attempts: int, verif_result: dict, status: str, runtime_res: dict = None) -> str:
        if status in ('verified', 'verified_with_warnings'):
            repair_str = f" after {attempts} repair loop{'s' if attempts > 1 else ''}" if attempts > 0 else ""
            warn_str = f" ({verif_result['warning_count']} warnings)" if verif_result['warning_count'] > 0 else ""
            if runtime_res and runtime_res.get('executed'):
                runtime_str = " Runtime checks passed."
            elif runtime_res and runtime_res.get('reason') and 'skipped: requires' in runtime_res['reason']:
                runtime_str = f" ({runtime_res['reason']})."
            else:
                runtime_str = " Runtime checks were not run."
            return f"{file_count} project files generated. Static verification passed{repair_str}{warn_str}.{runtime_str}"

        # status == 'needs_attention'
        error_lines = [f"• {i['file']}: {i['message']}" for i in verif_result['issues'] if i['severity'] == 'error']
        err_list = "\n".join(error_lines[:5])
        return f"{file_count} files generated. {verif_result['error_count']} verification issue(s) remain that could not be auto-fixed:\n{err_list}"

