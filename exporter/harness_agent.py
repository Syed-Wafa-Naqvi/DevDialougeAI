import json
import logging
import re
from llm_engine.router import LLMRouter
from generator.path_safety import PathSafetyManager

logger = logging.getLogger(__name__)

class AIHarnessPackager:
    """
    Universal AI Packager Agent:
    Uses the user's configured AI key to inspect any codebase (Python, JavaScript/TypeScript,
    Go, Rust, Java, Flutter, C++, etc.) and dynamically generate missing build manifests,
    environment configuration, and 1-click startup runners so the project runs turn-key in any IDE.
    """

    @classmethod
    def generate_harness(cls, session, existing_files: dict, project_name: str) -> dict:
        file_list = sorted(list(existing_files.keys()))
        display_title = project_name.replace('_', ' ')

        # Gather brief snippets to help the AI detect the language & framework
        file_snippets = []
        for path in file_list[:8]:
            snippet = existing_files[path][:350].strip()
            file_snippets.append(f"--- File: {path} ---\n{snippet}")
        snippets_text = "\n\n".join(file_snippets)

        # Retrieve requirements summary or concept from session messages
        summary = getattr(session, 'summary_text', '') or ""
        if not summary:
            for msg in reversed(list(session.messages.order_by('id'))):
                if "project concept" in msg.content.lower() or "requirements summary" in msg.content.lower():
                    summary = msg.content[:1200]
                    break

        prompt = (
            f"Project Name: {display_title}\n"
            f"Generated Codebase Files:\n" + "\n".join([f"- {p}" for p in file_list]) + "\n\n"
            f"Codebase Snippets:\n{snippets_text}\n\n"
            f"Project Specification Context:\n{summary}\n\n"
            "TASK:\n"
            "You are an autonomous DevOps & Build Engineer AI agent. "
            "Analyze the programming language, framework, and architecture used in this codebase (e.g. Node.js/TypeScript, Python, Go, Rust, Java, Flutter, C++, Ruby, etc.).\n"
            "Generate ALL missing setup, dependency manifests, and 1-click runner scripts so that ANY developer can extract this ZIP and run it in any IDE (VS Code, PyCharm, Cursor, etc.) or terminal with ZERO manual configuration.\n\n"
            "MANDATORY OUTPUT FILES (only generate if not already present in the codebase):\n"
            "1. Dependency/Package Manifest (e.g. package.json, requirements.txt, go.mod, Cargo.toml, pom.xml, etc.).\n"
            "2. One-click runner script for Unix/macOS: `run.sh` (complete executable script that installs dependencies, sets up virtualenv/tools if needed, and starts the development server or runs the app).\n"
            "3. One-click runner script for Windows: `run.bat` (batch script doing the equivalent).\n"
            "4. `.gitignore` appropriate for this language.\n"
            "5. Turnkey `README.md` with: project overview, 1-click start command, and step-by-step IDE instructions.\n"
            "6. Any missing core entry points or configuration files necessary for this codebase to compile or run.\n\n"
            "RESPONSE FORMAT:\n"
            "Return ONLY a valid JSON object matching this schema:\n"
            "{\n"
            "  \"detected_language\": \"python|javascript|typescript|go|rust|java|other\",\n"
            "  \"files\": [\n"
            "    {\"path\": \"run.sh\", \"content\": \"...\"},\n"
            "    {\"path\": \"requirements.txt\", \"content\": \"...\"}\n"
            "  ]\n"
            "}\n"
            "Do NOT include conversational text outside the JSON."
        )

        system_prompt = (
            "You are an autonomous DevOps & Build Engineer AI agent. "
            "Generate complete, working project build files, manifests, and startup scripts in JSON format."
        )

        new_files = {}

        try:
            raw_response = LLMRouter.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                purpose='harness_generation',
                session=session
            )
            parsed = cls._parse_json_response(raw_response)
            if parsed and isinstance(parsed.get('files'), list):
                for f in parsed['files']:
                    path = f.get('path', '').strip()
                    content = f.get('content', '')
                    if path and path not in existing_files:
                        try:
                            safe_path = PathSafetyManager.validate_path(path)
                            new_files[safe_path] = content
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"AI Harness Agent invocation warning: {e}")

        # Ensure fallback coverage if AI was unavailable or omitted essential runner files
        cls._apply_fallback_harness(existing_files, new_files, project_name)

        # Sanity check: Ensure manifests match the actual languages present
        has_py_files = any(p.endswith('.py') for p in existing_files)
        if not has_py_files and "requirements.txt" in new_files:
            del new_files["requirements.txt"]

        has_js_files = any(p.endswith(('.js', '.jsx', '.ts', '.tsx')) for p in existing_files)
        if not has_js_files and "package.json" in new_files:
            del new_files["package.json"]

        has_dart_files = any(p.endswith('.dart') for p in existing_files) or "pubspec.yaml" in existing_files
        if has_dart_files:
            if "requirements.txt" in new_files:
                del new_files["requirements.txt"]
            # If runner contains python commands for a dart project, replace with flutter runner
            if "run.sh" in new_files and ("python" in new_files["run.sh"] or "pip" in new_files["run.sh"]):
                new_files["run.sh"] = (
                    "#!/usr/bin/env bash\n"
                    "set -e\n"
                    f"echo '🚀 Starting Flutter Project: {display_title}...'\n"
                    "if ! command -v flutter >/dev/null 2>&1; then\n"
                    "    for cand in \"$HOME/flutter/bin\" \"$HOME/development/flutter/bin\" \"$HOME/.flutter/bin\" \"/snap/bin\" \"/opt/flutter/bin\"; do\n"
                    "        if [ -x \"$cand/flutter\" ]; then\n"
                    "            export PATH=\"$cand:$PATH\"\n"
                    "            break\n"
                    "        fi\n"
                    "    done\n"
                    "fi\n"
                    "if ! command -v flutter >/dev/null 2>&1; then\n"
                    "    echo '❌ Flutter SDK not found in PATH.'\n"
                    "    echo '💡 If installed, add it to your PATH: export PATH=\"$HOME/flutter/bin:$PATH\"'\n"
                    "    echo '   Or install from https://flutter.dev/docs/get-started/install'\n"
                    "    exit 1\n"
                    "fi\n"
                    "echo '📦 Fetching Flutter dependencies...'\n"
                    "if [ ! -d \"web\" ] && [ ! -d \"linux\" ] && [ ! -d \"android\" ] && [ ! -d \"windows\" ] && [ ! -d \"macos\" ]; then\n"
                    "    echo '📱 Generating native platform targets (web, desktop, mobile)...'\n"
                    "    flutter create . --suppress-analytics\n"
                    "fi\n"
                    "flutter pub get\n"
                    "echo '⚡ Launching Flutter App...'\n"
                    "flutter run -d chrome || flutter run\n"
                )
            if "run.bat" in new_files and ("python" in new_files["run.bat"] or "pip" in new_files["run.bat"]):
                new_files["run.bat"] = (
                    "@echo off\n"
                    f"echo Starting Flutter Project: {display_title}...\n"
                    "where flutter >nul 2>nul\n"
                    "if %errorlevel% neq 0 (\n"
                    "    if exist \"%USERPROFILE%\\flutter\\bin\\flutter.bat\" set \"PATH=%USERPROFILE%\\flutter\\bin;%PATH%\"\n"
                    "    if exist \"C:\\src\\flutter\\bin\\flutter.bat\" set \"PATH=C:\\src\\flutter\\bin;%PATH%\"\n"
                    "    if exist \"C:\\flutter\\bin\\flutter.bat\" set \"PATH=C:\\flutter\\bin;%PATH%\"\n"
                    ")\n"
                    "where flutter >nul 2>nul\n"
                    "if %errorlevel% neq 0 (\n"
                    "    echo [ERROR] Flutter SDK not found in PATH. Install from https://flutter.dev\n"
                    "    pause\n"
                    "    exit /b 1\n"
                    ")\n"
                    "echo Fetching Flutter dependencies...\n"
                    "if not exist \"web\" if not exist \"windows\" if not exist \"android\" (\n"
                    "    echo Generating native platform targets...\n"
                    "    call flutter create . --suppress-analytics\n"
                    ")\n"
                    "call flutter pub get\n"
                    "echo Launching Flutter App...\n"
                    "call flutter run -d chrome || call flutter run\n"
                    "pause\n"
                )

        return new_files


    @classmethod
    def _parse_json_response(cls, text: str) -> dict:
        text = text.strip()
        if "```" in text:
            matches = re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
            if matches:
                text = matches[0].strip()
        try:
            return json.loads(text)
        except Exception:
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start:end+1])
                except Exception:
                    pass
        return {}

    @classmethod
    def _apply_fallback_harness(cls, existing_files: dict, new_files: dict, project_name: str):
        """
        Guarantees that every downloaded project has turnkey runners and manifests
        even if the AI call times out or is in mock mode.
        """
        all_files = {**existing_files, **new_files}
        display_title = project_name.replace('_', ' ')

        # Detect primary language based on file extensions
        has_dart = any(p.endswith('.dart') for p in all_files) or "pubspec.yaml" in all_files
        has_js = any(p.endswith(('.js', '.jsx', '.ts', '.tsx', '.mjs')) for p in all_files)
        has_py = any(p.endswith('.py') for p in all_files)
        has_go = any(p.endswith('.go') for p in all_files)
        has_rust = any(p.endswith('.rs') for p in all_files)

        # 0. Flutter / Dart
        if has_dart:
            clean_proj_name = re.sub(r'[^a-zA-Z0-9_]', '_', project_name.lower()).strip('_') or 'flutter_app'
            if "pubspec.yaml" not in all_files:
                new_files["pubspec.yaml"] = (
                    f"name: {clean_proj_name}\n"
                    f"description: \"{display_title} generated by DevDialogue AI.\"\n"
                    "publish_to: 'none'\n"
                    "version: 1.0.0+1\n\n"
                    "environment:\n"
                    "  sdk: '>=3.0.0 <4.0.0'\n\n"
                    "dependencies:\n"
                    "  flutter:\n"
                    "    sdk: flutter\n"
                    "  shared_preferences: ^2.2.2\n"
                    "  cupertino_icons: ^1.0.6\n\n"
                    "dev_dependencies:\n"
                    "  flutter_test:\n"
                    "    sdk: flutter\n"
                    "  flutter_lints: ^3.0.0\n\n"
                    "flutter:\n"
                    "  uses-material-design: true\n"
                )
            if "run.sh" not in all_files:
                new_files["run.sh"] = (
                    "#!/usr/bin/env bash\n"
                    "set -e\n"
                    f"echo '🚀 Starting Flutter Project: {display_title}...'\n"
                    "if ! command -v flutter >/dev/null 2>&1; then\n"
                    "    for cand in \"$HOME/flutter/bin\" \"$HOME/development/flutter/bin\" \"$HOME/.flutter/bin\" \"/snap/bin\" \"/opt/flutter/bin\"; do\n"
                    "        if [ -x \"$cand/flutter\" ]; then\n"
                    "            export PATH=\"$cand:$PATH\"\n"
                    "            break\n"
                    "        fi\n"
                    "    done\n"
                    "fi\n"
                    "if ! command -v flutter >/dev/null 2>&1; then\n"
                    "    echo '❌ Flutter SDK not found in PATH.'\n"
                    "    echo '💡 If installed, add it to your PATH: export PATH=\"$HOME/flutter/bin:$PATH\"'\n"
                    "    echo '   Or install from https://flutter.dev/docs/get-started/install'\n"
                    "    exit 1\n"
                    "fi\n"
                    "echo '📦 Fetching Flutter dependencies...'\n"
                    "if [ ! -d \"web\" ] && [ ! -d \"linux\" ] && [ ! -d \"android\" ] && [ ! -d \"windows\" ] && [ ! -d \"macos\" ]; then\n"
                    "    echo '📱 Generating native platform targets (web, desktop, mobile)...'\n"
                    "    flutter create . --suppress-analytics\n"
                    "fi\n"
                    "flutter pub get\n"
                    "echo '⚡ Launching Flutter App...'\n"
                    "flutter run -d chrome || flutter run\n"
                )
            if "run.bat" not in all_files:
                new_files["run.bat"] = (
                    "@echo off\n"
                    f"echo Starting Flutter Project: {display_title}...\n"
                    "where flutter >nul 2>nul\n"
                    "if %errorlevel% neq 0 (\n"
                    "    if exist \"%USERPROFILE%\\flutter\\bin\\flutter.bat\" set \"PATH=%USERPROFILE%\\flutter\\bin;%PATH%\"\n"
                    "    if exist \"C:\\src\\flutter\\bin\\flutter.bat\" set \"PATH=C:\\src\\flutter\\bin;%PATH%\"\n"
                    "    if exist \"C:\\flutter\\bin\\flutter.bat\" set \"PATH=C:\\flutter\\bin;%PATH%\"\n"
                    ")\n"
                    "where flutter >nul 2>nul\n"
                    "if %errorlevel% neq 0 (\n"
                    "    echo [ERROR] Flutter SDK not found in PATH. Install from https://flutter.dev\n"
                    "    pause\n"
                    "    exit /b 1\n"
                    ")\n"
                    "echo Fetching Flutter dependencies...\n"
                    "if not exist \"web\" if not exist \"windows\" if not exist \"android\" (\n"
                    "    echo Generating native platform targets...\n"
                    "    call flutter create . --suppress-analytics\n"
                    ")\n"
                    "call flutter pub get\n"
                    "echo Launching Flutter App...\n"
                    "call flutter run -d chrome || call flutter run\n"
                    "pause\n"
                )
            if ".gitignore" not in all_files:
                new_files[".gitignore"] = (
                    ".dart_tool/\n"
                    ".packages\n"
                    "build/\n"
                    ".pub/\n"
                    "*.lock\n"
                    ".flutter-plugins\n"
                    ".flutter-plugins-dependencies\n"
                )


        # 1. Node.js / JavaScript / TypeScript
        elif has_js and not has_py:
            if "package.json" not in all_files:
                new_files["package.json"] = json.dumps({
                    "name": project_name.lower(),
                    "version": "1.0.0",
                    "description": f"{display_title} generated by DevDialogue AI",
                    "main": "server.js" if "server.js" in all_files else "index.js",
                    "scripts": {
                        "start": "node server.js" if "server.js" in all_files else "node index.js",
                        "dev": "nodemon server.js" if "server.js" in all_files else "node index.js"
                    },
                    "dependencies": {
                        "express": "^4.19.2",
                        "cors": "^2.8.5"
                    }
                }, indent=2)
            if "run.sh" not in all_files:
                new_files["run.sh"] = (
                    "#!/usr/bin/env bash\nset -e\n"
                    f"echo '🚀 Starting {display_title}...'\n"
                    "npm install\n"
                    "npm start\n"
                )
            if "run.bat" not in all_files:
                new_files["run.bat"] = f"@echo off\necho Starting {display_title}...\ncall npm install\ncall npm start\npause\n"
            if ".gitignore" not in all_files:
                new_files[".gitignore"] = "node_modules/\n.env\n*.log\n.DS_Store\n"

        # 2. Go
        elif has_go:
            if "go.mod" not in all_files:
                new_files["go.mod"] = f"module {project_name.lower()}\n\ngo 1.22\n"
            if "run.sh" not in all_files:
                new_files["run.sh"] = f"#!/usr/bin/env bash\nset -e\necho '🚀 Starting {display_title}...'\ngo run .\n"
            if "run.bat" not in all_files:
                new_files["run.bat"] = f"@echo off\necho Starting {display_title}...\ngo run .\npause\n"
            if ".gitignore" not in all_files:
                new_files[".gitignore"] = "*.exe\n*.exe~\n*.dll\n*.so\n*.dylib\n"

        # 3. Rust
        elif has_rust:
            if "Cargo.toml" not in all_files:
                new_files["Cargo.toml"] = (
                    f"[package]\nname = \"{project_name.lower()}\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n[dependencies]\n"
                )
            if "run.sh" not in all_files:
                new_files["run.sh"] = f"#!/usr/bin/env bash\nset -e\necho '🚀 Starting {display_title}...'\ncargo run\n"
            if "run.bat" not in all_files:
                new_files["run.bat"] = f"@echo off\necho Starting {display_title}...\ncargo run\npause\n"
            if ".gitignore" not in all_files:
                new_files[".gitignore"] = "target/\nCargo.lock\n"

        # 4. Python (Django / FastAPI / Flask / General)
        else:
            if "requirements.txt" not in all_files:
                if any(k in all_files for k in ['models.py', 'views.py', 'manage.py']):
                    new_files["requirements.txt"] = "django>=5.0,<6.0\nrequests>=2.31.0\n"
                elif "main.py" in all_files:
                    new_files["requirements.txt"] = "fastapi>=0.110.0\nuvicorn>=0.28.0\nrequests>=2.31.0\n"
                else:
                    new_files["requirements.txt"] = "requests>=2.31.0\n"

            if "run.sh" not in all_files:
                new_files["run.sh"] = (
                    "#!/usr/bin/env bash\n"
                    "set -e\n"
                    f"echo '🚀 Starting {display_title}...'\n\n"
                    "PY_BIN=''\n"
                    "for cand in python3.13 python3.12 python3.11 python3 python; do\n"
                    "    if command -v \"$cand\" >/dev/null 2>&1; then\n"
                    "        if \"$cand\" -c 'import ensurepip' >/dev/null 2>&1; then\n"
                    "            PY_BIN=\"$cand\"\n"
                    "            break\n"
                    "        fi\n"
                    "    fi\n"
                    "done\n"
                    "if [ -z \"$PY_BIN\" ]; then PY_BIN='python3'; fi\n\n"
                    "if [ -d 'venv' ] && [ ! -f 'venv/bin/activate' ] && [ ! -f 'venv/Scripts/activate' ]; then\n"
                    "    rm -rf venv\n"
                    "fi\n"
                    "if [ ! -d 'venv' ]; then\n"
                    "    \"$PY_BIN\" -m venv venv || python3 -m venv venv || python -m venv venv\n"
                    "fi\n"
                    "source venv/bin/activate\n"
                    "pip install -r requirements.txt\n"
                    + ("python manage.py makemigrations app || true\npython manage.py migrate\npython manage.py runserver 127.0.0.1:8000\n"
                       if any("manage.py" in p or "models.py" in p for p in all_files)
                       else "python main.py\n")
                )

            if "run.bat" not in all_files:
                new_files["run.bat"] = (
                    "@echo off\n"
                    f"echo Starting {display_title}...\n"
                    "if not exist venv ( python -m venv venv )\n"
                    "call venv\\Scripts\\activate.bat\n"
                    "pip install -r requirements.txt\n"
                    + ("python manage.py makemigrations app\npython manage.py migrate\npython manage.py runserver 127.0.0.1:8000\n"
                       if any("manage.py" in p or "models.py" in p for p in all_files)
                       else "python main.py\n")
                    + "pause\n"
                )

            if ".gitignore" not in all_files:
                new_files[".gitignore"] = "venv/\n__pycache__/\n*.py[cod]\ndb.sqlite3\n*.log\n.DS_Store\n"

        # 5. Ensure comprehensive, turnkey README.md exists
        all_final_files = {**existing_files, **new_files}
        new_files["README.md"] = cls._build_turnkey_readme(
            display_title=display_title,
            all_files=all_final_files,
            has_dart=has_dart,
            has_py=has_py,
            has_js=has_js,
            has_go=has_go,
            has_rust=has_rust
        )

    @classmethod
    def _build_turnkey_readme(cls, display_title: str, all_files: dict, has_dart: bool, has_py: bool, has_js: bool, has_go: bool, has_rust: bool) -> str:
        files_list = "\n".join([f"- `{p}`" for p in sorted(all_files.keys()) if p != "README.md"])

        if has_dart:
            return (
                f"# {display_title}\n\n"
                "Generated by **DevDialogue AI** — Lead Systems Architect.\n\n"
                "This project is a complete, production-ready **Flutter (Dart)** application configured with Material 3 design and local state/persistence. It is packaged with 1-click launch scripts and is ready to run in **any IDE** (VS Code, Android Studio, IntelliJ) or terminal.\n\n"
                "---\n\n"
                "## ⚡ Option 1: 1-Click Startup (Recommended)\n\n"
                "- **macOS / Linux**:\n"
                "  ```bash\n"
                "  ./run.sh\n"
                "  ```\n"
                "- **Windows**:\n"
                "  Double-click `run.bat` (or run `run.bat` in Command Prompt):\n"
                "  ```cmd\n"
                "  run.bat\n"
                "  ```\n\n"
                "*The runner script will verify your Flutter installation, download dependencies via `flutter pub get`, and launch the application immediately.*\n\n"
                "---\n\n"
                "## 🛠️ Option 2: Run in VS Code (Visual Studio Code)\n\n"
                "1. **Open the project folder** in VS Code:\n"
                "   `File > Open Folder...` and select this extracted directory.\n"
                "2. **Install Flutter Extension**:\n"
                "   If not already installed, install the official **Flutter** extension (by Dart Code) from the Extensions tab (`Ctrl+Shift+X`).\n"
                "3. **Fetch Dependencies**:\n"
                "   VS Code will prompt you to run `flutter pub get`, or you can open the integrated terminal (`Ctrl+` `) and run:\n"
                "   ```bash\n"
                "   flutter pub get\n"
                "   ```\n"
                "4. **Select a Target Device / Browser**:\n"
                "   Click on the device selector in the bottom-right status bar (choose Chrome, Android Emulator, iOS Simulator, or Desktop).\n"
                "5. **Launch the App**:\n"
                "   Press **`F5`** (or go to `Run > Start Debugging`).\n\n"
                "---\n\n"
                "## 📱 Option 3: Run in Android Studio / IntelliJ\n\n"
                "1. Open Android Studio and choose **Open** to select this project directory.\n"
                "2. If prompted, click **Get dependencies** (or run `flutter pub get` in the built-in terminal).\n"
                "3. Select your desired emulator or connected device from the device dropdown at the top.\n"
                "4. Click the green **Play (▶)** button to launch.\n\n"
                "---\n\n"
                "## 💻 Option 4: Manual Terminal Run (Step-by-Step)\n\n"
                "1. **Ensure Flutter is installed**:\n"
                "   ```bash\n"
                "   flutter doctor\n"
                "   ```\n"
                "2. **Install dependencies**:\n"
                "   ```bash\n"
                "   flutter pub get\n"
                "   ```\n"
                "3. **Run automated test suite**:\n"
                "   ```bash\n"
                "   flutter test\n"
                "   ```\n"
                "4. **Launch the application**:\n"
                "   - To run on your default connected device / emulator:\n"
                "     ```bash\n"
                "     flutter run\n"
                "     ```\n"
                "   - To run directly in your web browser (Chrome):\n"
                "     ```bash\n"
                "     flutter run -d chrome\n"
                "     ```\n\n"
                "---\n\n"
                "## 📂 Architecture & File Breakdown\n\n"
                f"{files_list}\n\n"
                "- **`pubspec.yaml`**: The primary Flutter package manifest declaring dependencies (like `shared_preferences`, `cupertino_icons`) and asset configurations.\n"
                "- **`lib/main.dart`**: Application entrypoint configuring the Material 3 color scheme and root widget hierarchy.\n"
                "- **`lib/screens/`**: UI screens and user interaction views.\n"
                "- **`lib/widgets/`**: Reusable component widgets.\n"
                "- **`lib/models/`**: Domain models and JSON serialization logic.\n"
                "- **`test/widget_test.dart`**: Automated widget smoke tests.\n"
                "- **`run.sh` / `run.bat`**: 1-click startup automation for Unix and Windows.\n\n"
                "---\n\n"
                "## ❓ Troubleshooting\n\n"
                "- **\"flutter: command not found\"**:\n"
                "  Make sure the Flutter SDK is installed and added to your system's PATH. See [Flutter Installation Guide](https://flutter.dev/docs/get-started/install).\n"
                "- **\"No connected devices found\"**:\n"
                "  Run `flutter run -d chrome` to launch the app inside Google Chrome without needing a mobile emulator.\n"
            )

        elif has_py:
            is_django = any("manage.py" in p or "models.py" in p for p in all_files)
            run_cmd = "python manage.py runserver 127.0.0.1:8000" if is_django else "python main.py"
            migration_step = (
                "4. **Apply database migrations**:\n"
                "   ```bash\n"
                "   python manage.py makemigrations app\n"
                "   python manage.py migrate\n"
                "   ```\n"
                "5. "
            ) if is_django else "4. "
            return (
                f"# {display_title}\n\n"
                "Generated by **DevDialogue AI** — Lead Systems Architect.\n\n"
                "This project is a complete, runnable **Python** application configured with turnkey dependencies and virtual environment scripts.\n\n"
                "---\n\n"
                "## ⚡ Option 1: 1-Click Startup (Recommended)\n\n"
                "- **macOS / Linux**:\n"
                "  ```bash\n"
                "  ./run.sh\n"
                "  ```\n"
                "- **Windows**:\n"
                "  Double-click `run.bat` or run in Command Prompt:\n"
                "  ```cmd\n"
                "  run.bat\n"
                "  ```\n\n"
                "*The runner script will automatically create a clean virtual environment (`venv`), install dependencies from `requirements.txt`, apply database migrations (if applicable), and launch the application.*\n\n"
                "---\n\n"
                "## 🛠️ Option 2: Open in Any IDE (VS Code / PyCharm / Cursor)\n\n"
                "1. Open this extracted folder in your IDE (`File > Open Folder`).\n"
                "2. Create and activate a virtual environment:\n"
                "   ```bash\n"
                "   python3 -m venv venv\n"
                "   source venv/bin/activate       # On Windows: venv\\Scripts\\activate\n"
                "   ```\n"
                "3. Install dependencies:\n"
                "   ```bash\n"
                "   pip install -r requirements.txt\n"
                "   ```\n"
                f"{migration_step}**Start the application**:\n"
                "   ```bash\n"
                f"   {run_cmd}\n"
                "   ```\n\n"
                "---\n\n"
                "## 📂 Architecture & File Breakdown\n\n"
                f"{files_list}\n"
            )

        elif has_js:
            return (
                f"# {display_title}\n\n"
                "Generated by **DevDialogue AI** — Lead Systems Architect.\n\n"
                "This project is a complete **Node.js** application ready to run in any IDE or terminal.\n\n"
                "---\n\n"
                "## ⚡ Option 1: 1-Click Startup (Recommended)\n\n"
                "- **macOS / Linux**:\n"
                "  ```bash\n"
                "  ./run.sh\n"
                "  ```\n"
                "- **Windows**:\n"
                "  Double-click `run.bat` or run:\n"
                "  ```cmd\n"
                "  run.bat\n"
                "  ```\n\n"
                "---\n\n"
                "## 🛠️ Option 2: Manual Terminal Run\n\n"
                "1. Install dependencies:\n"
                "   ```bash\n"
                "   npm install\n"
                "   ```\n"
                "2. Start development server:\n"
                "   ```bash\n"
                "   npm start\n"
                "   ```\n\n"
                "---\n\n"
                "## 📂 Architecture & File Breakdown\n\n"
                f"{files_list}\n"
            )

        elif has_go:
            return (
                f"# {display_title}\n\n"
                "Generated by **DevDialogue AI** — Lead Systems Architect.\n\n"
                "This project is a complete, runnable **Go (Golang)** application ready to run in any IDE or terminal.\n\n"
                "---\n\n"
                "## ⚡ Option 1: 1-Click Startup (Recommended)\n\n"
                "- **macOS / Linux**:\n"
                "  ```bash\n"
                "  ./run.sh\n"
                "  ```\n"
                "- **Windows**:\n"
                "  Double-click `run.bat` or run in Command Prompt:\n"
                "  ```cmd\n"
                "  run.bat\n"
                "  ```\n\n"
                "---\n\n"
                "## 🛠️ Option 2: Run in VS Code / GoLand\n\n"
                "1. Open this folder in your IDE.\n"
                "2. Ensure the Go extension / SDK is enabled.\n"
                "3. Run automated tests:\n"
                "   ```bash\n"
                "   go test ./...\n"
                "   ```\n"
                "4. Start the app:\n"
                "   ```bash\n"
                "   go run main.go\n"
                "   ```\n\n"
                "---\n\n"
                "## 📂 Architecture & File Breakdown\n\n"
                f"{files_list}\n"
            )

        elif has_rust:
            return (
                f"# {display_title}\n\n"
                "Generated by **DevDialogue AI** — Lead Systems Architect.\n\n"
                "This project is a complete, runnable **Rust** application configured with Cargo.\n\n"
                "---\n\n"
                "## ⚡ Option 1: 1-Click Startup (Recommended)\n\n"
                "- **macOS / Linux**:\n"
                "  ```bash\n"
                "  ./run.sh\n"
                "  ```\n"
                "- **Windows**:\n"
                "  Double-click `run.bat` or run in Command Prompt:\n"
                "  ```cmd\n"
                "  run.bat\n"
                "  ```\n\n"
                "---\n\n"
                "## 🛠️ Option 2: Run via Cargo in Any IDE\n\n"
                "1. Open this project directory in your IDE (VS Code with `rust-analyzer` or RustRover).\n"
                "2. Run automated tests:\n"
                "   ```bash\n"
                "   cargo test\n"
                "   ```\n"
                "3. Compile and execute:\n"
                "   ```bash\n"
                "   cargo run\n"
                "   ```\n\n"
                "---\n\n"
                "## 📂 Architecture & File Breakdown\n\n"
                f"{files_list}\n"
            )

        else:
            return (
                f"# {display_title}\n\n"
                "Generated by **DevDialogue AI** — Lead Systems Architect.\n\n"
                "This project is fully packaged and ready to run in any IDE or terminal.\n\n"
                "## ⚡ Quick Start (1-Click Run)\n\n"
                "- **macOS / Linux**:\n"
                "  ```bash\n"
                "  ./run.sh\n"
                "  ```\n"
                "- **Windows**:\n"
                "  Double-click `run.bat` or run in Command Prompt:\n"
                "  ```cmd\n"
                "  run.bat\n"
                "  ```\n\n"
                "## 📂 Included Project Files\n\n"
                f"{files_list}\n"
            )


