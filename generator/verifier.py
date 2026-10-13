import ast
import hashlib
import html.parser
import json
import re
import sys

class StaticVerifier:
    PACKAGE_MAPPINGS = {
        'rest_framework': 'djangorestframework',
        'dotenv': 'python-dotenv',
        'yaml': 'PyYAML',
        'jwt': 'PyJWT',
        'PIL': 'Pillow',
        'bs4': 'beautifulsoup4',
        'cv2': 'opencv-python',
        'sklearn': 'scikit-learn',
    }

    STDLIB_MODULES = getattr(sys, 'stdlib_module_names', {
        'os', 'sys', 're', 'json', 'math', 'datetime', 'time', 'random', 'hashlib',
        'collections', 'itertools', 'functools', 'pathlib', 'typing', 'unittest',
        'io', 'ast', 'difflib', 'html', 'sqlite3', 'email', 'logging', 'subprocess'
    })

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
    def verify_project(cls, files: dict, plan_data: dict = None) -> dict:
        """
        Runs static analysis across all project files without execution.
        Returns a dict: {'passed': bool, 'error_count': int, 'warning_count': int, 'issues': list}
        """
        issues = []
        py_files = {path: content for path, content in files.items() if path.endswith('.py')}
        ast_cache = {}

        # 1. Parse Python Syntax & Cache ASTs
        for path, content in py_files.items():
            try:
                ast_tree = ast.parse(content, filename=path)
                ast_cache[path] = ast_tree
            except SyntaxError as e:
                issues.append(cls._create_issue(
                    file_path=path,
                    line=e.lineno or 1,
                    severity='error',
                    check='syntax',
                    message=f"SyntaxError: {e.msg}"
                ))

        # 2. Python AST Checks (Imports, Contracts, Local Resolution)
        declared_requirements = cls._extract_declared_requirements(files, plan_data)

        for path, tree in ast_cache.items():
            file_issues = cls._verify_python_file(path, tree, py_files, ast_cache, declared_requirements, plan_data)
            issues.extend(file_issues)

        # 3. Django Specific Checks (Settings, Templates, URLs)
        django_issues = cls._verify_django_architecture(files, ast_cache)
        issues.extend(django_issues)

        # 4. Non-Python File Validation
        other_issues = cls._verify_non_python_files(files)
        issues.extend(other_issues)

        error_count = sum(1 for i in issues if i['severity'] == 'error')
        warning_count = sum(1 for i in issues if i['severity'] == 'warning')

        return {
            'passed': error_count == 0,
            'error_count': error_count,
            'warning_count': warning_count,
            'issues': issues
        }

    @classmethod
    def _extract_declared_requirements(cls, files: dict, plan_data: dict) -> set:
        reqs = set()
        if plan_data and 'dependencies' in plan_data:
            for dep in plan_data.get('dependencies', []):
                pkg = re.split(r'[<>=!~]', dep)[0].strip().lower()
                reqs.add(pkg)

        if 'requirements.txt' in files:
            for line in files['requirements.txt'].splitlines():
                line_clean = line.strip()
                if line_clean and not line_clean.startswith('#'):
                    pkg = re.split(r'[<>=!~]', line_clean)[0].strip().lower()
                    reqs.add(pkg)

        return reqs

    @classmethod
    def _get_module_exported_symbols(cls, tree: ast.AST) -> set:
        symbols = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        symbols.add(target.id)
        return symbols

    @classmethod
    def _verify_python_file(cls, path: str, tree: ast.AST, py_files: dict, ast_cache: dict, declared_reqs: set, plan_data: dict) -> list:
        issues = []
        defined_symbols = cls._get_module_exported_symbols(tree)

        # Plan Contract Check
        if plan_data and 'files' in plan_data:
            for f_info in plan_data['files']:
                if f_info.get('path') == path:
                    for exp in f_info.get('exports', []):
                        exp_name = exp.get('name') if isinstance(exp, dict) else str(exp)
                        if exp_name and exp_name not in defined_symbols:
                            issues.append(cls._create_issue(
                                file_path=path,
                                line=1,
                                severity='error',
                                check='contract',
                                message=f"Missing promised plan export '{exp_name}'."
                            ))

        # Import Resolution & Third-Party Package Checks
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_module = alias.name.split('.')[0]
                    cls._check_import_module(path, node.lineno, top_module, alias.name, py_files, declared_reqs, issues)

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                # Handle relative imports (e.g. from .models import Task)
                if node.level > 0:
                    dir_parts = path.split('/')[:-1]
                    if node.level > len(dir_parts):
                        rel_path = ""
                    else:
                        target_dir = "/".join(dir_parts[:len(dir_parts) - node.level + 1])
                        rel_path = f"{target_dir}/{module_name}.py" if module_name else f"{target_dir}/__init__.py"
                    
                    # Normalize path
                    rel_path = rel_path.replace('//', '/').lstrip('/')
                    matched_file = None
                    for pf in py_files:
                        if pf == rel_path or pf.endswith(f"/{rel_path}"):
                            matched_file = pf
                            break

                    if matched_file and matched_file in ast_cache:
                        target_symbols = cls._get_module_exported_symbols(ast_cache[matched_file])
                        for alias in node.names:
                            if alias.name != '*' and alias.name not in target_symbols:
                                issues.append(cls._create_issue(
                                    file_path=path,
                                    line=node.lineno,
                                    severity='error',
                                    check='local_import_resolution',
                                    message=f"Imports '{alias.name}' from '{rel_path}', which does not define it."
                                ))
                    elif not matched_file:
                        issues.append(cls._create_issue(
                            file_path=path,
                            line=node.lineno,
                            severity='error',
                            check='local_import_resolution',
                            message=f"Relative import target '{rel_path}' does not exist."
                        ))
                else:
                    top_module = module_name.split('.')[0]
                    cls._check_import_module(path, node.lineno, top_module, module_name, py_files, declared_reqs, issues)

                    # Local module symbol check
                    target_file = None
                    module_as_path = module_name.replace('.', '/') + '.py'
                    for pf in py_files:
                        if pf == module_as_path or pf.endswith(f"/{module_as_path}"):
                            target_file = pf
                            break

                    if target_file and target_file in ast_cache:
                        target_symbols = cls._get_module_exported_symbols(ast_cache[target_file])
                        for alias in node.names:
                            if alias.name != '*' and alias.name not in target_symbols:
                                issues.append(cls._create_issue(
                                    file_path=path,
                                    line=node.lineno,
                                    severity='error',
                                    check='local_import_resolution',
                                    message=f"Imports '{alias.name}' from '{target_file}', which does not define it."
                                ))

        return issues

    @classmethod
    def _check_import_module(cls, file_path: str, line: int, top_module: str, full_module: str, py_files: dict, declared_reqs: set, issues: list):
        if not top_module or top_module in cls.STDLIB_MODULES:
            return

        # Check if local module
        is_local = False
        full_module_path = full_module.replace('.', '/') + '.py'
        full_pkg_path = full_module.replace('.', '/') + '/__init__.py'

        for pf in py_files:
            if pf == full_module_path or pf.endswith(f"/{full_module_path}") or pf == full_pkg_path or pf.endswith(f"/{full_pkg_path}") or pf.startswith(f"{top_module}/"):
                is_local = True
                break

        if is_local:
            return

        # Third-party requirement check
        mapped_pkg = cls.PACKAGE_MAPPINGS.get(top_module, top_module).lower()
        if declared_reqs and mapped_pkg not in declared_reqs and top_module.lower() not in declared_reqs:
            issues.append(cls._create_issue(
                file_path=file_path,
                line=line,
                severity='warning',
                check='third_party_dependency',
                message=f"Imports '{top_module}' (mapped package '{mapped_pkg}'), which is not declared in requirements.txt or plan dependencies."
            ))

    @classmethod
    def _verify_django_architecture(cls, files: dict, ast_cache: dict) -> list:
        issues = []
        templates_in_project = {p for p in files if 'template' in p.lower() or p.endswith('.html')}

        for path, tree in ast_cache.items():
            content = files.get(path, '')

            # Check render template references
            for match in re.finditer(r"render\s*\(\s*request\s*,\s*['\"]([^'\"]+)['\"]", content):
                tpl_name = match.group(1)
                tpl_found = any(tp.endswith(tpl_name) for tp in templates_in_project)
                if not tpl_found:
                    line_no = content[:match.start()].count('\n') + 1
                    issues.append(cls._create_issue(
                        file_path=path,
                        line=line_no,
                        severity='error',
                        check='missing_template',
                        message=f"References template '{tpl_name}', which does not exist in templates directory."
                    ))

            # Check urls.py view imports / unresolved views
            if path.endswith('urls.py'):
                local_symbols = cls._get_module_exported_symbols(tree)
                # Collect all imported names in urls.py
                imported_names = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imported_names.add(alias.asname or alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            imported_names.add(alias.asname or alias.name)

                all_known_views = local_symbols.union(imported_names)

                for match in re.finditer(r"path\s*\(\s*['\"][^'\"]*['\"]\s*,\s*([a-zA-Z0-9_]+(?:\.as_view\(\))?)", content):
                    raw_ref = match.group(1)
                    view_ref = raw_ref.split('.')[0]  # Handle view_fn or views.view_fn
                    line_no = content[:match.start()].count('\n') + 1

                    if view_ref not in all_known_views:
                        issues.append(cls._create_issue(
                            file_path=path,
                            line=line_no,
                            severity='error',
                            check='unresolved_url_view',
                            message=f"URL pattern references view '{raw_ref}', which is not imported or defined in urls.py."
                        ))

        return issues

    @classmethod
    def _verify_non_python_files(cls, files: dict) -> list:
        issues = []
        for path, content in files.items():
            if path.endswith('.json'):
                try:
                    json.loads(content)
                except Exception as e:
                    issues.append(cls._create_issue(
                        file_path=path,
                        line=1,
                        severity='error',
                        check='json_syntax',
                        message=f"Invalid JSON format: {str(e)}"
                    ))

            elif path == 'requirements.txt':
                for idx, line in enumerate(content.splitlines()):
                    line_clean = line.strip()
                    if line_clean and not line_clean.startswith('#'):
                        if not re.match(r'^[a-zA-Z0-9_\-\.\[\]]+([<>=!~]+[a-zA-Z0-9_\-\.]+)?$', line_clean):
                            issues.append(cls._create_issue(
                                file_path=path,
                                line=idx + 1,
                                severity='warning',
                                check='requirements_format',
                                message=f"Invalid requirement string format: '{line_clean}'"
                            ))

        return issues
