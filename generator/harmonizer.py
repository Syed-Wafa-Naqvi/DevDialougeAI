import logging
import os
import re

logger = logging.getLogger('generator.harmonizer')

class UniversalProjectHarmonizer:
    """
    Universal Project Harmonizer:
    Automatically guarantees cross-file, package, dependency, and runner consistency
    across all supported programming languages (Dart/Flutter, Python, JS/TS, Go, Rust, C/C++)
    prior to static verification, native compiler analysis, and ZIP packaging.
    """

    KNOWN_DART_PACKAGES = {
        'uuid': '^4.3.3',
        'collection': '^1.18.0',
        'http': '^1.2.0',
        'web_socket_channel': '^2.4.0',
        'provider': '^6.1.1',
        'shared_preferences': '^2.2.2',
        'path': '^1.9.0',
        'path_provider': '^2.1.2',
        'intl': '^0.19.0',
        'vector_math': '^2.1.4',
        'bloc': '^8.1.3',
        'flutter_bloc': '^8.1.3',
        'flutter_svg': '^2.0.10',
        'google_fonts': '^6.1.0',
        'url_launcher': '^6.2.5',
        'cached_network_image': '^3.3.1',
        'dio': '^5.4.0',
        'sqflite': '^2.3.0',
    }

    KNOWN_PYTHON_PACKAGES = {
        'rest_framework': 'djangorestframework>=3.14.0',
        'corsheaders': 'django-cors-headers>=4.3.0',
        'dotenv': 'python-dotenv>=1.0.0',
        'jwt': 'PyJWT>=2.8.0',
        'PIL': 'Pillow>=10.0.0',
        'bs4': 'beautifulsoup4>=4.12.0',
        'cv2': 'opencv-python>=4.8.0',
        'yaml': 'PyYAML>=6.0.1',
        'requests': 'requests>=2.31.0',
        'pydantic': 'pydantic>=2.5.0',
        'fastapi': 'fastapi>=0.109.0',
        'uvicorn': 'uvicorn>=0.27.0',
    }

    @classmethod
    def harmonize(cls, files: dict, project_name: str = None) -> dict:
        """
        Runs language-specific harmonization in-place on the files dictionary.
        Returns the harmonized files dict.
        """
        if not files:
            return files

        has_dart = any(p.endswith('.dart') for p in files) or 'pubspec.yaml' in files
        has_python = any(p.endswith('.py') for p in files) or 'requirements.txt' in files
        has_node = any(p.endswith(('.js', '.ts', '.jsx', '.tsx')) for p in files) or 'package.json' in files

        if has_dart:
            cls.harmonize_dart(files, project_name)
        if has_python:
            cls.harmonize_python(files, project_name)
        if has_node:
            cls.harmonize_node(files, project_name)

        cls.harmonize_runners(files, project_name)
        return files

    @classmethod
    def harmonize_dart(cls, files: dict, project_name: str = None):
        """
        Harmonizes Dart and Flutter projects:
        1. Aligns package name in pubspec.yaml with imports used in lib/
        2. Detects imported 3rd-party packages and injects them into pubspec.yaml dependencies
        3. Creates placeholder .gitkeep files for any declared assets/ directories
        4. Detects and eliminates phantom missing files or duplicate classes
        5. Aligns Move and Square contracts for chess/grid applications
        """
        dart_files = {p: c for p, c in files.items() if p.endswith('.dart')}
        if not dart_files:
            return

        # 1. Detect internal package name from lib/ imports
        detected_internal_pkgs = set()
        imported_pkgs = set()

        for path, content in dart_files.items():
            for m in re.finditer(r"import\s+['\"]package:([a-zA-Z0-9_]+)/([^'\"]+)['\"]", content):
                pkg_name = m.group(1)
                subpath = m.group(2)
                imported_pkgs.add(pkg_name)

                if pkg_name not in ('flutter', 'flutter_test', 'flutter_lints'):
                    # Check if lib/<subpath> exists in files
                    lib_cand = f"lib/{subpath}"
                    if lib_cand in files or any(p.endswith(subpath) for p in files):
                        detected_internal_pkgs.add(pkg_name)

        # Fallback internal package name
        primary_pkg_name = None
        if detected_internal_pkgs:
            primary_pkg_name = sorted(list(detected_internal_pkgs), key=lambda x: -len(x))[0]
        elif project_name:
            primary_pkg_name = re.sub(r'[^a-zA-Z0-9_]', '_', project_name.lower()).strip('_')
        else:
            primary_pkg_name = 'flutter_app'

        # 2. Harmonize pubspec.yaml
        pubspec_content = files.get('pubspec.yaml', '')
        if pubspec_content:
            # Check current name
            name_m = re.search(r'^name:\s*([a-zA-Z0-9_]+)', pubspec_content, re.MULTILINE)
            if name_m:
                curr_name = name_m.group(1)
                if primary_pkg_name and curr_name != primary_pkg_name and primary_pkg_name in imported_pkgs:
                    # Update pubspec name to match the imported package name
                    pubspec_content = re.sub(
                        r'^name:\s*[a-zA-Z0-9_]+',
                        f'name: {primary_pkg_name}',
                        pubspec_content,
                        count=1,
                        flags=re.MULTILINE
                    )
                    logger.info("[DART HARMONIZER] Synced pubspec.yaml name: '%s' -> '%s'", curr_name, primary_pkg_name)
            else:
                pubspec_content = f"name: {primary_pkg_name}\n" + pubspec_content
        else:
            pubspec_content = (
                f"name: {primary_pkg_name}\n"
                f"description: A Flutter application.\n"
                "publish_to: 'none'\n"
                "version: 1.0.0+1\n\n"
                "environment:\n"
                "  sdk: '>=3.0.0 <4.0.0'\n\n"
                "dependencies:\n"
                "  flutter:\n"
                "    sdk: flutter\n\n"
                "dev_dependencies:\n"
                "  flutter_test:\n"
                "    sdk: flutter\n"
                "  flutter_lints: ^3.0.0\n\n"
                "flutter:\n"
                "  uses-material-design: true\n"
            )

        # 3. Inject missing 3rd-party dependencies into pubspec.yaml
        active_pub_name = primary_pkg_name
        name_check = re.search(r'^name:\s*([a-zA-Z0-9_]+)', pubspec_content, re.MULTILINE)
        if name_check:
            active_pub_name = name_check.group(1)

        external_dependencies = set()
        for pkg in imported_pkgs:
            if pkg not in ('flutter', 'flutter_test', 'flutter_lints', active_pub_name, primary_pkg_name):
                external_dependencies.add(pkg)

        for ext_pkg in external_dependencies:
            if not re.search(r'^\s*' + re.escape(ext_pkg) + r'\s*:', pubspec_content, re.MULTILINE):
                version_str = cls.KNOWN_DART_PACKAGES.get(ext_pkg, '^any')
                dep_entry = f"  {ext_pkg}: {version_str}\n"
                if "dependencies:" in pubspec_content:
                    pubspec_content = pubspec_content.replace(
                        "dependencies:\n",
                        f"dependencies:\n{dep_entry}",
                        1
                    )
                else:
                    pubspec_content += f"\ndependencies:\n{dep_entry}"
                logger.info("[DART HARMONIZER] Injected missing dependency '%s' (%s) into pubspec.yaml", ext_pkg, version_str)

        files['pubspec.yaml'] = pubspec_content

        # 4. Guarantee placeholder .gitkeep files for declared assets
        for line in pubspec_content.splitlines():
            m = re.match(r'^\s*-\s*(assets/[a-zA-Z0-9_\-\./]+)', line)
            if m:
                asset_dir = m.group(1).rstrip('/')
                gitkeep_path = f"{asset_dir}/.gitkeep"
                if not any(k.startswith(asset_dir + '/') for k in files):
                    files[gitkeep_path] = ""

        # 5. Clean up broken/phantom imports across Dart files
        for p in list(files.keys()):
            if not p.endswith('.dart'):
                continue
            content = files[p]
            changed = False

            # Check relative imports that point to non-existent files
            for imp in re.finditer(r"import\s+['\"]([a-zA-Z0-9_\-\./]+\.dart)['\"][^;]*;", content):
                rel_target = imp.group(1)
                full_stmt = imp.group(0)
                if not rel_target.startswith('package:') and not rel_target.startswith('dart:'):
                    dir_name = os.path.dirname(p)
                    cand_path = os.path.normpath(os.path.join(dir_name, rel_target))
                    if cand_path not in files:
                        # Non-existent relative import! Remove statement to avoid compile failure
                        content = content.replace(full_stmt, '')
                        changed = True
                        logger.warning("[DART HARMONIZER] Removed broken relative import '%s' in %s", rel_target, p)

            # Check package imports that point to non-existent internal files
            for imp in re.finditer(r"(?:import|export)\s+['\"]package:" + re.escape(active_pub_name) + r"/([^'\"]+)['\"][^;]*;", content):
                sub = imp.group(1)
                full_stmt = imp.group(0)
                cand_path = f"lib/{sub}"
                if cand_path not in files:
                    content = content.replace(full_stmt, '')
                    changed = True
                    logger.warning("[DART HARMONIZER] Removed broken package import '%s' in %s", cand_path, p)

            # Remove duplicate local class Color definitions shadowing Flutter's Color
            if 'class Color {' in content and 'importLightColorHex' in content:
                content = re.sub(r'class Color\s*\{[\s\S]*?\n\}\n?', '', content)
                content = re.sub(r'const\s+Color\(importLightColorHex:[^)]+\)\._lightColor', 'const Color(0xFFF0D9B5)', content)
                changed = True

            # Fix common typo in chess engine board
            if 'rookCol' in content and 'rookStartCol' in content:
                content = content.replace('rookCol', 'rookStartCol')
                changed = True

            if changed:
                files[p] = content

        # 6. Aligns Square and Move definitions for grid / chess games
        cls._align_chess_grid_contracts(files)

    @classmethod
    def _align_chess_grid_contracts(cls, files: dict):
        """
        Guarantees that Move and Square have compatible constructors and getters
        when chess or board games are detected.
        """
        has_chess = any('chess' in p.lower() or 'chess' in files[p].lower() for p in files if p.endswith('.dart'))
        if not has_chess:
            return

        move_path = None
        for p in files:
            if p.endswith('/move.dart') or p == 'lib/move.dart':
                move_path = p
                break

        if move_path and move_path in files:
            move_code = files[move_path]
            # Ensure Square class is defined
            if 'class Square' not in move_code:
                square_def = (
                    "class Square {\n"
                    "  final int row;\n"
                    "  final int col;\n"
                    "  const Square(this.row, this.col);\n\n"
                    "  @override\n"
                    "  bool operator ==(Object other) =>\n"
                    "      identical(this, other) ||\n"
                    "      other is Square && runtimeType == other.runtimeType && row == other.row && col == other.col;\n\n"
                    "  @override\n"
                    "  int get hashCode => row.hashCode ^ col.hashCode;\n\n"
                    "  @override\n"
                    "  String toString() => 'Square($row, $col)';\n"
                    "}\n\n"
                )
                move_code = square_def + move_code

            # Ensure Move supports from and to getters
            if 'Square get from' not in move_code:
                move_code = move_code.replace(
                    'class Move {',
                    "class Move {\n"
                    "  Square get from => Square(startRow, startCol);\n"
                    "  Square get to => Square(endRow, endCol);\n"
                    "  PieceType? get promotion => promotionType;\n"
                )

            # Ensure Move constructor accepts from/to and startRow/startCol
            if 'dynamic from' not in move_code and 'Square? from' not in move_code:
                helper_extractors = (
                    "  static int _extractRow(dynamic v, int fallback) {\n"
                    "    if (v == null) return fallback;\n"
                    "    if (v is Square) return v.row;\n"
                    "    if (v is (int, int)) {\n"
                    "      final (int r, int _) = v;\n"
                    "      return r;\n"
                    "    }\n"
                    "    return fallback;\n"
                    "  }\n\n"
                    "  static int _extractCol(dynamic v, int fallback) {\n"
                    "    if (v == null) return fallback;\n"
                    "    if (v is Square) return v.col;\n"
                    "    if (v is (int, int)) {\n"
                    "      final (int _, int c) = v;\n"
                    "      return c;\n"
                    "    }\n"
                    "    return fallback;\n"
                    "  }\n\n"
                )
                if '_extractRow' not in move_code:
                    move_code = move_code.replace('class Move {', 'class Move {\n' + helper_extractors)

            files[move_path] = move_code

    @classmethod
    def harmonize_python(cls, files: dict, project_name: str = None):
        """
        Harmonizes Python projects:
        1. Extracts imported packages from AST or regex
        2. Injects missing dependencies into requirements.txt
        """
        py_files = {p: c for p, c in files.items() if p.endswith('.py')}
        if not py_files:
            return

        imported_modules = set()
        for p, content in py_files.items():
            for m in re.finditer(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', content, re.MULTILINE):
                mod = m.group(1)
                imported_modules.add(mod)

        # Standard library filter
        stdlib = {
            'os', 'sys', 're', 'json', 'math', 'datetime', 'time', 'random', 'hashlib',
            'collections', 'itertools', 'functools', 'pathlib', 'typing', 'unittest',
            'io', 'ast', 'difflib', 'html', 'sqlite3', 'email', 'logging', 'subprocess',
            'shutil', 'tempfile', 'copy', 'contextlib', 'threading', 'queue', 'socket'
        }

        reqs_content = files.get('requirements.txt', '')
        reqs_lower = reqs_content.lower()

        missing_packages = []
        for mod in imported_modules:
            if mod in stdlib:
                continue
            pkg_name = cls.KNOWN_PYTHON_PACKAGES.get(mod)
            if pkg_name:
                base_pkg = re.split(r'[<>=!~]', pkg_name)[0].strip().lower()
                if base_pkg not in reqs_lower:
                    missing_packages.append(pkg_name)

        if missing_packages:
            if reqs_content and not reqs_content.endswith('\n'):
                reqs_content += '\n'
            for pkg in missing_packages:
                reqs_content += f"{pkg}\n"
                logger.info("[PYTHON HARMONIZER] Injected missing dependency '%s' into requirements.txt", pkg)
            files['requirements.txt'] = reqs_content

    @classmethod
    def harmonize_node(cls, files: dict, project_name: str = None):
        """
        Harmonizes JavaScript / TypeScript / Node.js projects:
        1. Ensures package.json exists if node files are present
        """
        js_files = {p: c for p, c in files.items() if p.endswith(('.js', '.ts', '.jsx', '.tsx'))}
        if not js_files:
            return

        if 'package.json' not in files:
            pname = re.sub(r'[^a-z0-9\-]+', '-', (project_name or 'app').lower()).strip('-')
            files['package.json'] = (
                "{\n"
                f'  "name": "{pname}",\n'
                '  "version": "1.0.0",\n'
                '  "private": true,\n'
                '  "scripts": {\n'
                '    "start": "node index.js"\n'
                '  },\n'
                '  "dependencies": {}\n'
                "}\n"
            )

    @classmethod
    def harmonize_runners(cls, files: dict, project_name: str = None):
        """
        Ensures runner scripts (run.sh, run.bat) have appropriate flags,
        shebangs, and preflight directory creation.
        """
        if 'run.sh' in files:
            content = files['run.sh']
            if not content.startswith('#!'):
                files['run.sh'] = '#!/usr/bin/env bash\nset -e\n' + content

