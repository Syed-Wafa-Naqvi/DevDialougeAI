import hashlib
import importlib.util
import os
import re
import sys
import subprocess
import tempfile
from django.conf import settings
from generator.verifier import StaticVerifier

class RuntimeVerifier:
    @classmethod
    def _create_issue(cls, file_path: str, line: int, severity: str, check: str, message: str) -> dict:
        fingerprint_raw = f"{file_path}:{line}:{check}:{message}"
        fingerprint = hashlib.md5(fingerprint_raw.encode('utf-8')).hexdigest()
        return {
            'file': file_path,
            'line': line,
            'severity': severity,  # 'error' or 'warning'
            'check': check,
            'message': message,
            'fingerprint': fingerprint
        }

    @classmethod
    def _check_missing_packages(cls, files: dict, plan_data: dict = None) -> str:
        """
        Extracts requirements and checks if any required package is missing in current Python environment.
        Returns the missing package name if any, otherwise None.
        """
        required_pkgs = StaticVerifier._extract_declared_requirements(files, plan_data)
        if not required_pkgs:
            return None

        # Standard library or built-in modules
        std_lib = StaticVerifier.STDLIB_MODULES

        # Reverse mapping from package name to module name if needed
        pkg_to_module = {
            'djangorestframework': 'rest_framework',
            'python-dotenv': 'dotenv',
            'pyyaml': 'yaml',
            'pyjwt': 'jwt',
            'pillow': 'PIL',
            'beautifulsoup4': 'bs4',
            'opencv-python': 'cv2',
            'scikit-learn': 'sklearn',
        }

        for pkg in required_pkgs:
            pkg_lower = pkg.lower()
            if pkg_lower in std_lib:
                continue

            mod_name = pkg_to_module.get(pkg_lower, pkg_lower.replace('-', '_'))

            spec = importlib.util.find_spec(mod_name)
            if spec is None:
                return pkg

        return None

    @classmethod
    def _get_preexec_fn(cls):
        if sys.platform == "win32":
            return None

        def set_resource_limits():
            try:
                import resource
                # CPU time limit (15s soft, 20s hard)
                resource.setrlimit(resource.RLIMIT_CPU, (15, 20))
                # Virtual memory limit (512 MB)
                resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
                # File size limit (50 MB)
                resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
                # Max processes (50)
                resource.setrlimit(resource.RLIMIT_NPROC, (50, 50))
            except Exception:
                pass

        return set_resource_limits

    @classmethod
    def run_verification(cls, files: dict, user=None, plan_data: dict = None) -> dict:
        """
        Executes guarded runtime checks on generated project files.
        Returns verification result dictionary.
        """
        enabled = getattr(settings, 'RUNTIME_CHECKS_ENABLED', False)
        if not enabled:
            return {
                'executed': False,
                'passed': True,
                'reason': 'Runtime checks disabled',
                'error_count': 0,
                'warning_count': 0,
                'issues': []
            }

        if user is not None and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return {
                'executed': False,
                'passed': True,
                'reason': 'Runtime checks restricted to staff users',
                'error_count': 0,
                'warning_count': 0,
                'issues': []
            }

        # Check for missing packages
        missing_pkg = cls._check_missing_packages(files, plan_data)
        if missing_pkg:
            return {
                'executed': False,
                'passed': True,
                'reason': f"runtime checks skipped: requires {missing_pkg}",
                'error_count': 0,
                'warning_count': 0,
                'issues': []
            }

        workspace_root = getattr(settings, 'RUNTIME_CHECKS_WORKSPACE_ROOT', None)
        timeout = getattr(settings, 'RUNTIME_CHECKS_TIMEOUT', 60)
        python_exe = getattr(settings, 'RUNTIME_CHECKS_VENV_PATH', sys.executable) or sys.executable

        issues = []

        with tempfile.TemporaryDirectory(dir=workspace_root) as temp_dir:
            # Write project files into isolated temporary directory
            for path, content in files.items():
                full_path = os.path.join(temp_dir, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(content)

            # Minimal stripped environment
            minimal_env = {
                'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
                'HOME': temp_dir,
                'PYTHONDONTWRITEBYTECODE': '1',
                'DJANGO_SETTINGS_MODULE': 'config.settings',
                'SECRET_KEY': 'dummy-secret-key-for-runtime-check',
                'PYTHONPATH': temp_dir,
            }

            preexec_fn = cls._get_preexec_fn()

            # Sequence of runtime checks (stop at first failure)
            commands = [
                ([python_exe, "-m", "compileall", "-q", "."], "compileall"),
            ]

            has_manage_py = "manage.py" in files
            if has_manage_py:
                commands.append(([python_exe, "manage.py", "check"], "django_check"))
                commands.append(([python_exe, "manage.py", "makemigrations", "--check", "--dry-run"], "django_migrations"))

            # Test command detection
            has_tests = any('test' in p.lower() for p in files.keys())
            if has_tests:
                if has_manage_py:
                    commands.append(([python_exe, "manage.py", "test"], "django_test"))
                else:
                    if importlib.util.find_spec('pytest') is not None:
                        commands.append(([python_exe, "-m", "pytest", "-q"], "pytest"))
                    else:
                        commands.append(([python_exe, "-m", "unittest", "discover", "-q"], "unittest"))


            for cmd, check_name in commands:
                try:
                    res = subprocess.run(
                        cmd,
                        cwd=temp_dir,
                        env=minimal_env,
                        preexec_fn=preexec_fn,
                        capture_output=True,
                        text=True,
                        timeout=timeout
                    )
                except subprocess.TimeoutExpired:
                    issues.append(cls._create_issue(
                        file_path="runtime",
                        line=1,
                        severity="error",
                        check=check_name,
                        message=f"Runtime check command timed out after {timeout} seconds."
                    ))
                    break
                except Exception as e:
                    issues.append(cls._create_issue(
                        file_path="runtime",
                        line=1,
                        severity="error",
                        check=check_name,
                        message=f"Subprocess execution failed: {str(e)}"
                    ))
                    break

                if res.returncode != 0:
                    output = (res.stderr or res.stdout or "Command failed with return code %d" % res.returncode)[:20480]
                    parsed_issues = cls._parse_error_output(output, check_name, files)
                    issues.extend(parsed_issues)
                    break

        error_count = sum(1 for i in issues if i['severity'] == 'error')
        warning_count = sum(1 for i in issues if i['severity'] == 'warning')

        return {
            'executed': True,
            'passed': error_count == 0,
            'error_count': error_count,
            'warning_count': warning_count,
            'issues': issues
        }

    @classmethod
    def _parse_error_output(cls, output: str, check_name: str, files: dict) -> list:
        issues = []
        # Pattern for Python traceback: File "path/to/file.py", line 12, in function
        tb_pattern = re.compile(r'File ["\'](.*?)["\'], line (\d+)(?:, in (.*))?')

        matches = list(tb_pattern.finditer(output))
        if matches:
            for match in matches:
                filepath = match.group(1)
                line = int(match.group(2))
                rel_path = filepath
                # Clean temp path prefix if present
                for known_file in files.keys():
                    if filepath.endswith(known_file):
                        rel_path = known_file
                        break

                msg_line = output.strip().splitlines()[-1] if output.strip() else "Runtime error"
                issues.append(cls._create_issue(
                    file_path=rel_path,
                    line=line,
                    severity="error",
                    check=check_name,
                    message=f"Runtime error: {msg_line}"
                ))
        else:
            first_line = output.strip().splitlines()[0] if output.strip() else "Runtime check failed"
            issues.append(cls._create_issue(
                file_path="runtime",
                line=1,
                severity="error",
                check=check_name,
                message=f"Check '{check_name}' failed: {first_line[:200]}"
            ))

        return issues
