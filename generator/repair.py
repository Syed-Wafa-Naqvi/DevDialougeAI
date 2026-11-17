import logging
from generator.verifier import StaticVerifier
from generator.runtime_verifier import RuntimeVerifier
from generator.harmonizer import UniversalProjectHarmonizer
from generator.protocol import EditProtocolEngine, ProtocolValidationError
from llm_engine.router import LLMRouter
from chat.models import VerificationRun, ProjectFile, FileVersion

logger = logging.getLogger('generator.repair')

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

        # Pre-flight project harmonization
        UniversalProjectHarmonizer.harmonize(current_files)

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
        logger.info("🔧 [AUTO-REPAIR LOOP STARTED] Initial errors to resolve: %d | Max attempts: %d", len(prev_fingerprints), max_attempts)

        while attempts < max_attempts:
            attempts += 1
            failing_issues = [i for i in initial_verif['issues'] if i['severity'] == 'error']
            logger.info("🔧 [REPAIR ATTEMPT %d/%d] Targeting %d errors...", attempts, max_attempts, len(failing_issues))

            prompt = cls._build_repair_prompt(current_files, failing_issues, plan_data)

            raw_resp = LLMRouter.generate(
                prompt=prompt,
                system_prompt=cls.SYSTEM_PROMPT,
                provider_name=provider_name,
                purpose='repair',
                session=session,
                user=getattr(session, 'user', None)
            )

            try:
                payload = EditProtocolEngine.parse_payload(raw_resp)
                validated_ops = EditProtocolEngine.validate_operations(payload, current_files)
                candidate_files = EditProtocolEngine.apply_operations_atomically(validated_ops, current_files)
            except ProtocolValidationError:
                # If model response failed validation, allow next attempt
                continue

            # Re-verify candidate files
            candidate_verif = StaticVerifier.verify_project(candidate_files, plan_data=plan_data)
            if candidate_verif['error_count'] == 0:
                runtime_cand = RuntimeVerifier.run_verification(candidate_files, user=user, plan_data=plan_data)
                if runtime_cand.get('executed') and not runtime_cand['passed']:
                    candidate_verif = runtime_cand

            candidate_errors = candidate_verif['error_count']

            # Check if this attempt made progress
            if candidate_errors < initial_verif['error_count'] or candidate_errors == 0:
                logger.info("✅ [REPAIR PROGRESS] Errors reduced: %d -> %d", initial_verif['error_count'], candidate_errors)
                current_files = candidate_files
                initial_verif = candidate_verif
                prev_fingerprints = {i['fingerprint'] for i in candidate_verif['issues'] if i['severity'] == 'error'}
                cls._persist_repaired_files(session, current_files, validated_ops)
                cls._record_verification_run(session, initial_verif, level='static')

                if candidate_errors == 0:
                    break
            else:
                logger.warning("⚠️ [REPAIR ATTEMPT %d/%d] Errors did not decrease (%d -> %d). Retrying...",
                    attempts, max_attempts, initial_verif['error_count'], candidate_errors)

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
        import re
        from generator.code_builder import CodeBuilder

        issue_lines = [f"- File '{i['file']}' Line {i['line']} [{i['check']}]: {i['message']}" for i in issues]
        issues_text = "\n".join(issue_lines)

        failing_files = {i['file'] for i in issues if i['file'] in files}

        # Also detect referenced files in issue messages (e.g. "defined in package:.../board.dart" or "candidate in ...")
        for i in issues:
            msg = i.get('message', '')
            for m in re.finditer(r'[\'"]([a-zA-Z0-9_\-\./]+\.(?:dart|py|js|ts|jsx|tsx|yaml))[\'"]', msg):
                ref_path = m.group(1).lstrip('/')
                for p in files.keys():
                    if p.endswith(ref_path) or ref_path.endswith(p):
                        failing_files.add(p)

        file_snippets = []
        for path in sorted(failing_files):
            if path in files:
                file_snippets.append(f"=== File: {path} ===\n{files[path]}")

        snippets_text = "\n\n".join(file_snippets)

        # Include public signatures of other project files for cross-file alignment
        other_files = {p: c for p, c in files.items() if p not in failing_files}
        signatures = CodeBuilder.extract_signatures(other_files) if other_files else {}
        sig_snippets = [f"=== File Signatures: {p} ===\n{s}" for p, s in signatures.items() if s]
        sig_text = "\n\n".join(sig_snippets[:20])

        sig_section = f"\nOTHER PROJECT FILE SIGNATURES (FOR ALIGNING CALLERS & CONSTRUCTORS):\n{sig_text}\n" if sig_text else ""

        return (
            f"VERIFICATION & COMPILER ISSUES TO REPAIR:\n{issues_text}\n\n"
            f"FAILING & REFERENCED FILES CONTENT:\n{snippets_text}\n"
            f"{sig_section}\n"
            "MANDATORY REPAIR INSTRUCTIONS:\n"
            "1. Fix ALL compiler and verification errors above.\n"
            "2. Align constructor parameter names and types with callers. If callers pass no parameters, ensure constructors have optional/default parameters.\n"
            "3. If a method or getter is missing (e.g. 'isCheckmate', 'getValidMovesForPiece', 'getPiece'), implement it or correct the caller.\n"
            "4. In Dart: NEVER access library-private '_' members across files. Make members public if called from another file.\n"
            "5. Consolidate duplicate enums (e.g. 'PlayerColor') into a single file to eliminate colliding import errors.\n"
            "6. In conditions like `if (engine.makeMove(...))`, ensure the method returns `bool`, not `void`.\n"
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

