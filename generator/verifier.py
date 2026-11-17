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

        # 4. Django / Python N+1 Queries Checks (MANDATORY)
        n_plus_one_issues = cls._verify_n_plus_one_queries(files, ast_cache)
        issues.extend(n_plus_one_issues)

        # 5. Dart / Flutter Static & Semantic Checks
        dart_issues = cls._verify_dart_project(files)
        issues.extend(dart_issues)

        # 6. Non-Python File Validation
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
    def _verify_n_plus_one_queries(cls, files: dict, ast_cache: dict) -> list:
        issues = []
        # 1. Collect all model definitions and their ForeignKey / OneToOneField fields
        model_fks = {}
        for path, tree in ast_cache.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    fks = set()
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            if isinstance(item.value, ast.Call):
                                func = item.value.func
                                attr_name = func.attr if isinstance(func, ast.Attribute) else ''
                                if attr_name in ('ForeignKey', 'OneToOneField'):
                                    for target in item.targets:
                                        if isinstance(target, ast.Name):
                                            fks.add(target.id)
                    if fks:
                        model_fks[node.name] = fks

        # 2. Inspect for loops across all Python files
        for path, tree in ast_cache.items():
            var_select_related = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    var_name = node.targets[0].id
                    curr = node.value
                    while isinstance(curr, ast.Call):
                        if isinstance(curr.func, ast.Attribute) and curr.func.attr == 'select_related':
                            args = [a.value for a in curr.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                            var_select_related[var_name] = set(args)
                        curr = curr.func.value if isinstance(curr.func, ast.Attribute) else None

            for node in ast.walk(tree):
                if isinstance(node, ast.For):
                    target_name = node.target.id if isinstance(node.target, ast.Name) else None
                    iter_name = node.iter.id if isinstance(node.iter, ast.Name) else None
                    known_selected = set(var_select_related.get(iter_name, set()))

                    if isinstance(node.iter, ast.Call):
                        curr = node.iter
                        while isinstance(curr, ast.Call):
                            if isinstance(curr.func, ast.Attribute) and curr.func.attr == 'select_related':
                                args = [a.value for a in curr.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                                known_selected.update(args)
                            curr = curr.func.value if isinstance(curr.func, ast.Attribute) else None

                    for child in ast.walk(node):
                        # Detect queries executed inside a loop (classic N+1)
                        if isinstance(child, ast.Call):
                            func = child.func
                            if isinstance(func, ast.Attribute) and func.attr in ('get', 'filter', 'all', 'exclude'):
                                val = func.value
                                if isinstance(val, ast.Attribute) and val.attr == 'objects':
                                    mname = val.value.id if isinstance(val.value, ast.Name) else 'Model'
                                    issues.append(cls._create_issue(
                                        file_path=path,
                                        line=child.lineno,
                                        severity='error',
                                        check='n_plus_one_query',
                                        message=f"N+1 Query Hazard: Database query '{mname}.objects.{func.attr}()' executed inside a loop body. Use batch querying outside the loop with id__in or prefetch_related."
                                    ))

                        # Detect accessing foreign key relations in a loop without select_related
                        if target_name and isinstance(child, ast.Attribute):
                            sub_val = child.value
                            if isinstance(sub_val, ast.Attribute) and isinstance(sub_val.value, ast.Name) and sub_val.value.id == target_name:
                                rel_field = sub_val.attr
                                if rel_field not in known_selected and not rel_field.startswith('_') and rel_field not in ('objects', 'pk', 'id'):
                                    issues.append(cls._create_issue(
                                        file_path=path,
                                        line=child.lineno,
                                        severity='error',
                                        check='n_plus_one_query',
                                        message=f"N+1 Query Hazard: Accessing foreign relation '{rel_field}' on '{target_name}' in loop without select_related('{rel_field}'). Chain .select_related('{rel_field}') on the queryset."
                                    ))
        return issues

    @classmethod
    def _verify_dart_project(cls, files: dict) -> list:
        issues = []
        dart_files = {p: c for p, c in files.items() if p.endswith('.dart')}
        if not dart_files:
            return issues

        declared_enums = {}
        declared_classes = {}
        file_imports = {}

        for path, content in dart_files.items():
            imports = []
            for imp in re.finditer(r"import\s+['\"]([^'\"]+)['\"](?:\s+as\s+[a-zA-Z0-9_]+)?(?:\s+(?:hide|show)\s+([^;]+))?;", content):
                imp_path = imp.group(1)
                hidden = imp.group(2) or ''
                imports.append({'path': imp_path, 'hidden': [h.strip() for h in hidden.split(',') if h.strip()]})
            file_imports[path] = imports

            for m in re.finditer(r'enum\s+([A-Za-z0-9_]+)\s*\{([^}]+)\}', content):
                ename = m.group(1)
                vals = [v.strip().split('(')[0].strip() for v in m.group(2).split(',') if v.strip()]
                if ename not in declared_enums:
                    declared_enums[ename] = {}
                declared_enums[ename][path] = vals

            class_matches = list(re.finditer(r'class\s+([A-Za-z0-9_]+)(?:\s+extends\s+[A-Za-z0-9_]+)?(?:\s+implements\s+[A-Za-z0-9_,\s]+)?(?:\s+with\s+[A-Za-z0-9_,\s]+)?\s*\{', content))
            for i, cm in enumerate(class_matches):
                cname = cm.group(1)
                start = cm.end()
                end = class_matches[i+1].start() if i+1 < len(class_matches) else len(content)
                body = content[start:end]

                if cname not in declared_classes:
                    declared_classes[cname] = {}

                ctors = []
                for ctor_m in re.finditer(r'(?:const\s+)?(?:factory\s+)?\b' + cname + r'(?:\.[A-Za-z0-9_]+)?\s*\(([^)]*)\)', body):
                    params_str = ctor_m.group(1).strip()
                    required_params = []
                    all_params = []
                    named_m = re.search(r'\{([^}]+)\}', params_str)
                    if named_m:
                        for p in named_m.group(1).split(','):
                            p_clean = p.strip()
                            if p_clean:
                                is_req = p_clean.startswith('required ')
                                parts = p_clean.replace('required ', '').split('=')[0].strip().split()
                                p_name = parts[-1].replace('this.', '')
                                all_params.append(p_name)
                                if is_req and '=' not in p_clean:
                                    required_params.append(p_name)
                    ctors.append({'raw': params_str, 'required': required_params, 'all_named': all_params})

                methods = set()
                void_methods = set()
                for meth_m in re.finditer(r'^\s*([A-Za-z0-9_<>?,\s]+)\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)\s*(?:async\s*)?(?:\{|=>)', body, re.MULTILINE):
                    ret_type, mname = meth_m.group(1).strip(), meth_m.group(2).strip()
                    if mname != cname:
                        methods.add(mname)
                        if ret_type == 'void':
                            void_methods.add(mname)

                getters = set()
                for get_m in re.finditer(r'^\s*([A-Za-z0-9_<>?,\s]+)\s+get\s+([a-zA-Z0-9_]+)', body, re.MULTILINE):
                    getters.add(get_m.group(2).strip())

                declared_classes[cname][path] = {
                    'constructors': ctors,
                    'methods': methods,
                    'void_methods': void_methods,
                    'getters': getters
                }

        # Check 1: Colliding imports (e.g. PlayerColor defined in both board.dart and chess_engine.dart)
        for ename, file_map in declared_enums.items():
            if len(file_map) > 1:
                decl_paths = list(file_map.keys())
                for path, imps in file_imports.items():
                    imported_matches = []
                    for imp in imps:
                        for dp in decl_paths:
                            dp_base = dp.split('/')[-1]
                            if dp in imp['path'] or imp['path'].endswith(dp_base):
                                if ename not in imp['hidden']:
                                    imported_matches.append(dp)
                    if len(set(imported_matches)) > 1:
                        issues.append(cls._create_issue(
                            file_path=path,
                            line=1,
                            severity='error',
                            check='colliding_import',
                            message=f"'{ename}' is imported from both '{imported_matches[0]}' and '{imported_matches[1]}'. Consolidate the enum in a single shared file or use 'hide {ename}'."
                        ))

        # Check 2: Cross-file private calls (e.g. _board._initializeBoard() or _chessEngine._isInCheck())
        for path, content in dart_files.items():
            for m in re.finditer(r'\b([a-zA-Z0-9_]+)\s*\.\s*(_[a-zA-Z0-9_]+)\s*\(', content):
                target_var = m.group(1)
                private_member = m.group(2)
                if target_var not in ('this', 'super') and not private_member.startswith('__'):
                    line_no = content[:m.start()].count('\n') + 1
                    issues.append(cls._create_issue(
                        file_path=path,
                        line=line_no,
                        severity='error',
                        check='private_member_access',
                        message=f"Cannot call library-private method '{private_member}' on '{target_var}'. In Dart, leading underscore makes identifiers library-private. Remove leading '_' to make it public."
                    ))

        # Check 3: Constructor calls with missing required named arguments
        for path, content in dart_files.items():
            for cname, decl_map in declared_classes.items():
                for decl_file, cinfo in decl_map.items():
                    for ctor in cinfo['constructors']:
                        reqs = ctor.get('required', [])
                        if reqs:
                            for call_m in re.finditer(r'\b' + cname + r'\s*\(([^)]*)\)', content):
                                call_args = call_m.group(1)
                                line_no = content[:call_m.start()].count('\n') + 1
                                for req in reqs:
                                    if not re.search(r'\b' + req + r'\s*:', call_args):
                                        issues.append(cls._create_issue(
                                            file_path=path,
                                            line=line_no,
                                            severity='error',
                                            check='missing_constructor_param',
                                            message=f"Required named parameter '{req}' must be provided when instantiating '{cname}'."
                                        ))

        # Check 4: Void expression in condition or assignment (e.g. if (e.makeMove(1, 2)) where makeMove is void)
        for path, content in dart_files.items():
            for m in re.finditer(r'(?:if\s*\(|[=]\s*)[^;{}]*?\.([a-zA-Z0-9_]+)\s*\(', content):
                mname = m.group(1)
                for cname, decl_map in declared_classes.items():
                    for decl_file, cinfo in decl_map.items():
                        if mname in cinfo.get('void_methods', set()):
                            line_no = content[:m.start()].count('\n') + 1
                            issues.append(cls._create_issue(
                                file_path=path,
                                line=line_no,
                                severity='error',
                                check='void_in_condition',
                                message=f"Method '{mname}' on '{cname}' returns 'void' and cannot be evaluated in an 'if' condition or assigned to a variable. Update the method to return 'bool'."
                            ))

        # Check 5: Null safety on map lookup (e.g. _hasRookMoved[player].kingSide)
        for path, content in dart_files.items():
            for m in re.finditer(r'\[[^\]]+\]\.([a-zA-Z0-9_]+)', content):
                prop_name = m.group(1)
                line_no = content[:m.start()].count('\n') + 1
                issues.append(cls._create_issue(
                    file_path=path,
                    line=line_no,
                    severity='error',
                    check='null_safety_map_access',
                    message=f"Property '{prop_name}' cannot be accessed directly on a nullable map/record lookup. Use '?.' and '??' instead."
                ))

        # Check 6: Asset directory existence in pubspec.yaml
        if 'pubspec.yaml' in files:
            pub_content = files['pubspec.yaml']
            for line_idx, line in enumerate(pub_content.splitlines()):
                m = re.match(r'^\s*-\s*(assets/[a-zA-Z0-9_\-\./]+)', line)
                if m:
                    dir_path = m.group(1).rstrip('/')
                    has_asset = any(p.startswith(dir_path + '/') for p in files.keys())
                    if not has_asset:
                        issues.append(cls._create_issue(
                            file_path='pubspec.yaml',
                            line=line_idx + 1,
                            severity='warning',
                            check='missing_asset_dir',
                            message=f"Asset directory '{dir_path}/' is listed in pubspec.yaml but contains no files. Placeholder .gitkeep will be added."
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
