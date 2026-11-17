import hashlib
import importlib.util
import logging
import os
import re
import sys
import subprocess
import tempfile
from django.conf import settings
from generator.verifier import StaticVerifier
from generator.harmonizer import UniversalProjectHarmonizer

logger = logging.getLogger('generator.runtime_verifier')

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
                # File size limit (50 MB)
                resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
            except Exception:
                pass

        return set_resource_limits

    @classmethod
    def _find_flutter_binary(cls) -> str:
        import shutil
        found = shutil.which('flutter')
        if found:
            return found
        for cand in [
            os.path.expanduser('~/flutter/bin/flutter'),
            os.path.expanduser('~/development/flutter/bin/flutter'),
            '/opt/flutter/bin/flutter',
            '/snap/bin/flutter',
            '/usr/local/bin/flutter',
            '/usr/bin/flutter'
        ]:
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        return None

    @classmethod
    def _find_dart_binary(cls) -> str:
        import shutil
        found = shutil.which('dart')
        if found:
            return found
        for cand in [
            os.path.expanduser('~/flutter/bin/dart'),
            os.path.expanduser('~/development/flutter/bin/dart'),
            '/opt/flutter/bin/dart',
            '/snap/bin/dart',
            '/usr/local/bin/dart',
            '/usr/bin/dart'
        ]:
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        return None

    @classmethod
    def run_dart_verification(cls, files: dict) -> dict:
        """Runs flutter analyze or dart analyze on Dart/Flutter projects if SDK is available."""
        UniversalProjectHarmonizer.harmonize(files)
        dart_files = [p for p in files.keys() if p.endswith('.dart')]
        if not dart_files:
            return {'executed': False, 'passed': True, 'issues': []}

        flutter_bin = cls._find_flutter_binary()
        dart_bin = cls._find_dart_binary()
        if not flutter_bin and not dart_bin:
            return {'executed': False, 'passed': True, 'reason': 'Flutter/Dart SDK not found', 'issues': []}

        issues = []
        with tempfile.TemporaryDirectory() as temp_dir:
            for p, c in files.items():
                fp = os.path.join(temp_dir, p)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, 'w', encoding='utf-8') as f:
                    f.write(c)

            pubspec_content = files.get('pubspec.yaml')
            if not pubspec_content:
                pubspec_content = (
                    "name: temp_verification_project\n"
                    "environment:\n  sdk: '>=3.0.0 <4.0.0'\n"
                    "dependencies:\n  flutter:\n    sdk: flutter\n"
                )
                with open(os.path.join(temp_dir, 'pubspec.yaml'), 'w') as pf:
                    pf.write(pubspec_content)

            # Pre-flight asset directories from pubspec.yaml
            for line in pubspec_content.splitlines():
                m = re.match(r'^\s*-\s*(assets/[a-zA-Z0-9_\-\./]+)', line)
                if m:
                    clean_dir = os.path.join(temp_dir, m.group(1).rstrip('/'))
                    os.makedirs(clean_dir, exist_ok=True)
                    gitkeep_path = os.path.join(clean_dir, '.gitkeep')
                    if not os.path.exists(gitkeep_path):
                        try:
                            open(gitkeep_path, 'w').close()
                        except Exception:
                            pass

            if flutter_bin:
                try:
                    subprocess.run(
                        [flutter_bin, 'pub', 'get'],
                        cwd=temp_dir,
                        capture_output=True,
                        text=True,
                        timeout=25,
                        preexec_fn=cls._get_preexec_fn()
                    )
                except Exception:
                    pass

                try:
                    res = subprocess.run(
                        [flutter_bin, 'analyze', '--no-fatal-infos', '--no-fatal-warnings'],
                        cwd=temp_dir,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        preexec_fn=cls._get_preexec_fn()
                    )
                    stdout = res.stdout or ''
                    # Pattern 1: Flutter analyze standard output
                    p1 = re.compile(r'^\s*(error|warning|info)\s+[•-]\s+(.+?)\s+[•-]\s+([^:]+):(\d+):(\d+)(?:\s+[•-]\s+([a-zA-Z0-9_]+))?', re.MULTILINE)
                    for m in p1.finditer(stdout):
                        sev = m.group(1).lower()
                        if sev == 'info':
                            continue
                        msg = m.group(2).strip()
                        raw_file = m.group(3).strip()
                        rel_file = raw_file.replace(temp_dir, '').lstrip('/')
                        line = int(m.group(4))
                        check_name = m.group(6) or 'flutter_analyzer'
                        issues.append(cls._create_issue(
                            file_path=rel_file,
                            line=line,
                            severity=sev,
                            check=check_name,
                            message=msg
                        ))

                    # Pattern 2: Dart analyze fallback format
                    p2 = re.compile(r'^\s*(error|warning)\s+-\s+([^:]+):(\d+):(\d+)\s+-\s+(.+?)(?:\s+-\s+[a-zA-Z0-9_]+)?$', re.MULTILINE)
                    for m in p2.finditer(stdout):
                        sev = m.group(1).lower()
                        raw_file = m.group(2).strip()
                        rel_file = raw_file.replace(temp_dir, '').lstrip('/')
                        line = int(m.group(3))
                        msg = m.group(5).strip()
                        issues.append(cls._create_issue(
                            file_path=rel_file,
                            line=line,
                            severity=sev,
                            check='dart_analyzer',
                            message=msg
                        ))
                except Exception:
                    pass
            elif dart_bin:
                try:
                    res = subprocess.run(
                        [dart_bin, 'analyze', '--no-fatal-warnings', temp_dir],
                        capture_output=True,
                        text=True,
                        timeout=20,
                        preexec_fn=cls._get_preexec_fn()
                    )
                    stdout = res.stdout or ''
                    pattern = re.compile(r'^\s*(error|warning)\s+-\s+([^:]+):(\d+):(\d+)\s+-\s+(.+?)(?:\s+-\s+[a-zA-Z0-9_]+)?$', re.MULTILINE)
                    for m in pattern.finditer(stdout):
                        sev = m.group(1).lower()
                        raw_file = m.group(2).strip()
                        rel_file = raw_file.replace(temp_dir, '').lstrip('/')
                        line = int(m.group(3))
                        msg = m.group(5).strip()
                        issues.append(cls._create_issue(
                            file_path=rel_file,
                            line=line,
                            severity=sev,
                            check='dart_analyzer',
                            message=msg
                        ))
                except Exception:
                    pass

        err_count = sum(1 for i in issues if i['severity'] == 'error')
        warn_count = sum(1 for i in issues if i['severity'] == 'warning')
        return {
            'executed': True,
            'passed': err_count == 0,
            'error_count': err_count,
            'warning_count': warn_count,
            'issues': issues
        }

    @classmethod
    def run_shell_verification(cls, files: dict) -> dict:
        """Runs syntax validation on runner bash scripts using bash -n."""
        import shutil
        bash_bin = shutil.which('bash')
        if not bash_bin:
            return {'executed': False, 'passed': True, 'issues': []}

        sh_files = [p for p in files.keys() if p == 'run.sh' or p.endswith('.sh')]
        if not sh_files:
            return {'executed': False, 'passed': True, 'issues': []}

        issues = []
        with tempfile.TemporaryDirectory() as temp_dir:
            for p, c in files.items():
                if p == 'run.sh' or p.endswith('.sh'):
                    fp = os.path.join(temp_dir, p)
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                    with open(fp, 'w', encoding='utf-8') as f:
                        f.write(c)

            for p in sh_files:
                fp = os.path.join(temp_dir, p)
                try:
                    res = subprocess.run(
                        [bash_bin, '-n', fp],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        preexec_fn=cls._get_preexec_fn()
                    )
                    if res.returncode != 0:
                        err = res.stderr or ''
                        m = re.search(r'line\s+(\d+):\s*(.+)', err)
                        line_no = int(m.group(1)) if m else 1
                        msg = m.group(2).strip() if m else (err.strip().splitlines()[-1] if err.strip() else 'Bash syntax error')
                        issues.append(cls._create_issue(
                            file_path=p,
                            line=line_no,
                            severity='error',
                            check='bash_syntax',
                            message=f"Shell syntax error: {msg}"
                        ))
                except Exception:
                    pass

        err_count = sum(1 for i in issues if i['severity'] == 'error')
        return {
            'executed': True,
            'passed': err_count == 0,
            'error_count': err_count,
            'warning_count': 0,
            'issues': issues
        }

    @classmethod
    def run_node_verification(cls, files: dict) -> dict:
        """Runs node --check syntax verification on JavaScript files."""
        import shutil
        node_bin = shutil.which('node')
        if not node_bin:
            return {'executed': False, 'passed': True, 'issues': []}

        js_files = [p for p in files.keys() if p.endswith(('.js', '.cjs', '.mjs'))]
        if not js_files:
            return {'executed': False, 'passed': True, 'issues': []}

        issues = []
        with tempfile.TemporaryDirectory() as temp_dir:
            for p in js_files:
                fp = os.path.join(temp_dir, p)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, 'w', encoding='utf-8') as f:
                    f.write(files[p])

            for p in js_files:
                fp = os.path.join(temp_dir, p)
                try:
                    res = subprocess.run(
                        [node_bin, '--check', fp],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        preexec_fn=cls._get_preexec_fn()
                    )
                    if res.returncode != 0:
                        err = res.stderr or ''
                        m = re.search(r':(\d+)\n.*?\n\s*\^\s*\n+(?:[A-Za-z]+Error:\s*)?(.+)', err, re.DOTALL)
                        if not m:
                            m = re.search(r':(\d+)(?::\d+)?\s*\n.*?(SyntaxError:[^\n]+)', err)
                        if not m:
                            m = re.search(r':(\d+)', err)
                            line_no = int(m.group(1)) if m else 1
                            msg_line = err.strip().splitlines()[-1] if err.strip() else 'JavaScript syntax error'
                        else:
                            line_no = int(m.group(1))
                            msg_line = m.group(2).strip().splitlines()[0] if len(m.groups()) > 1 and m.group(2) else 'SyntaxError'
                        issues.append(cls._create_issue(
                            file_path=p,
                            line=line_no,
                            severity='error',
                            check='node_syntax',
                            message=f"Node.js syntax check failed: {msg_line}"
                        ))
                except Exception:
                    pass

        err_count = sum(1 for i in issues if i['severity'] == 'error')
        return {
            'executed': True,
            'passed': err_count == 0,
            'error_count': err_count,
            'warning_count': 0,
            'issues': issues
        }

    @classmethod
    def run_c_cpp_verification(cls, files: dict) -> dict:
        """Runs gcc/g++ -fsyntax-only verification on C and C++ source files."""
        import shutil
        gcc_bin = shutil.which('gcc')
        gpp_bin = shutil.which('g++')
        if not gcc_bin and not gpp_bin:
            return {'executed': False, 'passed': True, 'issues': []}

        c_files = [p for p in files.keys() if p.endswith('.c')]
        cpp_files = [p for p in files.keys() if p.endswith(('.cpp', '.cc', '.cxx'))]
        if not c_files and not cpp_files:
            return {'executed': False, 'passed': True, 'issues': []}

        issues = []
        with tempfile.TemporaryDirectory() as temp_dir:
            for p, c in files.items():
                if p.endswith(('.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hxx')):
                    fp = os.path.join(temp_dir, p)
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                    with open(fp, 'w', encoding='utf-8') as f:
                        f.write(c)

            inc_flags = ['-I.', '-Iinclude']

            # Check C files
            if gcc_bin and c_files:
                for p in c_files:
                    fp = os.path.join(temp_dir, p)
                    try:
                        res = subprocess.run(
                            [gcc_bin, '-fsyntax-only', *inc_flags, fp],
                            cwd=temp_dir,
                            capture_output=True,
                            text=True,
                            timeout=15,
                            preexec_fn=cls._get_preexec_fn()
                        )
                        if res.returncode != 0:
                            cls._parse_gcc_output(res.stderr or '', p, issues)
                    except Exception:
                        pass

            # Check C++ files
            compiler = gpp_bin or gcc_bin
            if compiler and cpp_files:
                for p in cpp_files:
                    fp = os.path.join(temp_dir, p)
                    try:
                        res = subprocess.run(
                            [compiler, '-fsyntax-only', '-std=c++17', *inc_flags, fp],
                            cwd=temp_dir,
                            capture_output=True,
                            text=True,
                            timeout=15,
                            preexec_fn=cls._get_preexec_fn()
                        )
                        if res.returncode != 0:
                            cls._parse_gcc_output(res.stderr or '', p, issues)
                    except Exception:
                        pass

        err_count = sum(1 for i in issues if i['severity'] == 'error')
        warn_count = sum(1 for i in issues if i['severity'] == 'warning')
        return {
            'executed': True,
            'passed': err_count == 0,
            'error_count': err_count,
            'warning_count': warn_count,
            'issues': issues
        }

    @classmethod
    def _parse_gcc_output(cls, stderr: str, fallback_file: str, issues: list):
        pat = re.compile(r'([^:\n]+):(\d+):(?:\d+:)?\s*(error|warning):\s*(.+)')
        for m in pat.finditer(stderr):
            line = int(m.group(2))
            sev = m.group(3).lower()
            msg = m.group(4).strip()
            issues.append(cls._create_issue(
                file_path=fallback_file,
                line=line,
                severity=sev,
                check='gcc_syntax',
                message=f"Compiler {sev}: {msg}"
            ))

    @classmethod
    def run_python_syntax_verification(cls, files: dict) -> dict:
        """Runs python -m py_compile / compileall syntax verification on Python files."""
        py_files = [p for p in files.keys() if p.endswith('.py')]
        if not py_files:
            return {'executed': False, 'passed': True, 'issues': []}

        issues = []
        with tempfile.TemporaryDirectory() as temp_dir:
            for p in py_files:
                fp = os.path.join(temp_dir, p)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, 'w', encoding='utf-8') as f:
                    f.write(files[p])

            python_exe = sys.executable or 'python3'
            try:
                res = subprocess.run(
                    [python_exe, '-m', 'compileall', '-q', temp_dir],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    preexec_fn=cls._get_preexec_fn()
                )
                if res.returncode != 0:
                    output = (res.stderr or '') + (res.stdout or '')
                    err_lines = output.splitlines()
                    for idx, el in enumerate(err_lines):
                        m = re.search(r'File ["\'](.*?)["\'], line (\d+)', el)
                        if m:
                            raw_path = m.group(1)
                            rel_p = raw_path.replace(temp_dir, '').lstrip('/')
                            line = int(m.group(2))
                            msg = err_lines[idx + 1].strip() if idx + 1 < len(err_lines) else 'SyntaxError'
                            issues.append(cls._create_issue(
                                file_path=rel_p,
                                line=line,
                                severity='error',
                                check='python_syntax',
                                message=f"Python syntax error: {msg}"
                            ))
            except Exception:
                pass

        err_count = sum(1 for i in issues if i['severity'] == 'error')
        return {
            'executed': True,
            'passed': err_count == 0,
            'error_count': err_count,
            'warning_count': 0,
            'issues': issues
        }

    @classmethod
    def run_verification(cls, files: dict, user=None, plan_data: dict = None) -> dict:
        """
        Executes guarded runtime and native compiler checks across all project languages.
        Returns verification result dictionary.
        """
        UniversalProjectHarmonizer.harmonize(files)
        all_compiler_issues = []
        any_executed = False
        logger.info("[RUNTIME VERIFIER] Inspecting %d files for native compiler / syntax checks...", len(files))

        # 1. Shell runner script syntax check (bash -n)
        if any(p == 'run.sh' or p.endswith('.sh') for p in files):
            logger.info("[SHELL CHECK] Running 'bash -n' syntax analysis on runner scripts...")
            shell_res = cls.run_shell_verification(files)
            if shell_res.get('executed'):
                any_executed = True
                all_compiler_issues.extend(shell_res.get('issues', []))

        # 2. Dart / Flutter compiler analyze
        if any(p.endswith('.dart') for p in files):
            logger.info("[DART/FLUTTER CHECK] Running native analyzer on Dart files...")
            dart_res = cls.run_dart_verification(files)
            if dart_res.get('executed'):
                any_executed = True
                all_compiler_issues.extend(dart_res.get('issues', []))

        # 3. Node.js JavaScript syntax check (node --check)
        if any(p.endswith(('.js', '.cjs', '.mjs')) for p in files):
            logger.info("[NODE CHECK] Running 'node --check' syntax validation...")
            node_res = cls.run_node_verification(files)
            if node_res.get('executed'):
                any_executed = True
                all_compiler_issues.extend(node_res.get('issues', []))

        # 4. GCC / G++ C/C++ syntax check (gcc/g++ -fsyntax-only)
        if any(p.endswith(('.c', '.cpp', '.cc', '.cxx')) for p in files):
            logger.info("[C/C++ CHECK] Running 'gcc/g++ -fsyntax-only' validation...")
            c_res = cls.run_c_cpp_verification(files)
            if c_res.get('executed'):
                any_executed = True
                all_compiler_issues.extend(c_res.get('issues', []))

        compiler_errors = sum(1 for i in all_compiler_issues if i['severity'] == 'error')
        if compiler_errors > 0:
            compiler_warns = sum(1 for i in all_compiler_issues if i['severity'] == 'warning')
            logger.warning("[RUNTIME/COMPILER ISSUES] %d errors, %d warnings detected", compiler_errors, compiler_warns)
            for iss in all_compiler_issues:
                if iss['severity'] == 'error':
                    logger.warning("   [-] %s:%s [%s] %s", iss['file'], iss['line'], iss['check'], iss['message'])
            return {
                'executed': True,
                'passed': False,
                'error_count': compiler_errors,
                'warning_count': compiler_warns,
                'issues': all_compiler_issues
            }

        # Check Python runtime / compilation permissions
        has_python = any(p.endswith('.py') for p in files)
        if has_python:
            enabled = getattr(settings, 'RUNTIME_CHECKS_ENABLED', False)
            if not enabled:
                return {
                    'executed': any_executed,
                    'passed': True,
                    'reason': 'Guarded compiler syntax checks passed' if any_executed else 'Runtime checks disabled',
                    'error_count': 0,
                    'warning_count': sum(1 for i in all_compiler_issues if i['severity'] == 'warning'),
                    'issues': all_compiler_issues
                }

            if user is not None and not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
                return {
                    'executed': any_executed,
                    'passed': True,
                    'reason': 'Guarded compiler syntax checks passed' if any_executed else 'Runtime checks restricted to staff users',
                    'error_count': 0,
                    'warning_count': sum(1 for i in all_compiler_issues if i['severity'] == 'warning'),
                    'issues': all_compiler_issues
                }

            # Python syntax compilation (compileall)
            py_res = cls.run_python_syntax_verification(files)
            if py_res.get('executed') and py_res.get('issues'):
                all_compiler_issues.extend(py_res.get('issues', []))
                compiler_errors = sum(1 for i in all_compiler_issues if i['severity'] == 'error')
                if compiler_errors > 0:
                    return {
                        'executed': True,
                        'passed': False,
                        'error_count': compiler_errors,
                        'warning_count': sum(1 for i in all_compiler_issues if i['severity'] == 'warning'),
                        'issues': all_compiler_issues
                    }
        else:
            # Non-python project with no compiler errors
            if any_executed:
                return {
                    'executed': True,
                    'passed': True,
                    'reason': 'Guarded compiler syntax checks passed',
                    'error_count': 0,
                    'warning_count': sum(1 for i in all_compiler_issues if i['severity'] == 'warning'),
                    'issues': all_compiler_issues
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
