import io
import re
import zipfile
from chat.models import GeneratedCode, ProjectFile, VerificationRun
from generator.path_safety import PathSafetyManager

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
                # Match explicit project selections (e.g. "Real-Time Collaboration Tool", "Todo App")
                lower = text.lower()
                domain_matches = [
                    'collaboration tool', 'collaboration', 'ecommerce', 'todo', 'blog', 
                    'chat app', 'social media', 'crm', 'inventory', 'marketplace', 
                    'booking', 'dashboard', 'real-time'
                ]
                if any(k in lower for k in domain_matches) and len(text) <= 50:
                    clean = re.sub(r'[^\w\s-]', '', text).strip()
                    if clean:
                        # Update session title if currently generic
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
        buffer = io.BytesIO()
        codes = list(GeneratedCode.objects.filter(session=session))
        project_files = list(ProjectFile.objects.filter(session=session))
        written_paths = set()
        project_name = cls.get_project_name(session)
        display_title = project_name.replace('_', ' ')

        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 1. Write user project files
            for pf in project_files:
                try:
                    safe_path = PathSafetyManager.validate_path(pf.path)
                    zf.writestr(safe_path, pf.content)
                    written_paths.add(safe_path)
                except Exception:
                    pass

            # 2. Write generated codes
            models_code = None
            views_code = None
            html_code = None

            for code_obj in codes:
                try:
                    safe_path = PathSafetyManager.validate_path(code_obj.module_name)
                    if safe_path not in written_paths:
                        zf.writestr(safe_path, code_obj.code_content)
                        written_paths.add(safe_path)

                    if "models.py" in safe_path:
                        models_code = code_obj.code_content
                    if "views.py" in safe_path:
                        views_code = code_obj.code_content
                    if "index.html" in safe_path:
                        html_code = code_obj.code_content
                except Exception:
                    pass

            # 3. Add Turnkey Runnable Django Project Harness if not already present
            if "manage.py" not in written_paths:
                # Add manage.py
                manage_py = (
                    "#!/usr/bin/env python\n"
                    '"""Django command-line utility for administrative tasks."""\n'
                    "import os\n"
                    "import sys\n\n"
                    "def main():\n"
                    "    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')\n"
                    "    try:\n"
                    "        from django.core.management import execute_from_command_line\n"
                    "    except ImportError as exc:\n"
                    "        raise ImportError(\n"
                    "            \"Couldn't import Django. Make sure it's installed in your virtual environment.\"\n"
                    "        ) from exc\n"
                    "    execute_from_command_line(sys.argv)\n\n"
                    "if __name__ == '__main__':\n"
                    "    main()\n"
                )
                info = zipfile.ZipInfo("manage.py")
                info.external_attr = 0o755 << 16  # rwxr-xr-x
                zf.writestr(info, manage_py)
                written_paths.add("manage.py")

            if "requirements.txt" not in written_paths:
                reqs_content = (
                    "django>=5.0,<6.0\n"
                    "requests>=2.31.0\n"
                )
                zf.writestr("requirements.txt", reqs_content)
                written_paths.add("requirements.txt")

            if "core/settings.py" not in written_paths and "settings.py" not in written_paths:
                settings_py = (
                    f'"""\nDjango settings for {display_title}.\nGenerated by DevDialogue AI.\n"""\n'
                    "from pathlib import Path\n"
                    "import os\n\n"
                    "BASE_DIR = Path(__file__).resolve().parent.parent\n\n"
                    "SECRET_KEY = 'devdialogue-turnkey-secret-key-change-in-production'\n"
                    "DEBUG = True\n"
                    "ALLOWED_HOSTS = ['*']\n\n"
                    "INSTALLED_APPS = [\n"
                    "    'django.contrib.admin',\n"
                    "    'django.contrib.auth',\n"
                    "    'django.contrib.contenttypes',\n"
                    "    'django.contrib.sessions',\n"
                    "    'django.contrib.messages',\n"
                    "    'django.contrib.staticfiles',\n"
                    "    'app',\n"
                    "]\n\n"
                    "MIDDLEWARE = [\n"
                    "    'django.middleware.security.SecurityMiddleware',\n"
                    "    'django.contrib.sessions.middleware.SessionMiddleware',\n"
                    "    'django.middleware.common.CommonMiddleware',\n"
                    "    'django.middleware.csrf.CsrfViewMiddleware',\n"
                    "    'django.contrib.auth.middleware.AuthenticationMiddleware',\n"
                    "    'django.contrib.messages.middleware.MessageMiddleware',\n"
                    "    'django.middleware.clickjacking.XFrameOptionsMiddleware',\n"
                    "]\n\n"
                    "ROOT_URLCONF = 'core.urls'\n\n"
                    "TEMPLATES = [\n"
                    "    {\n"
                    "        'BACKEND': 'django.template.backends.django.DjangoTemplates',\n"
                    "        'DIRS': [BASE_DIR / 'templates', BASE_DIR / 'app' / 'templates'],\n"
                    "        'APP_DIRS': True,\n"
                    "        'OPTIONS': {\n"
                    "            'context_processors': [\n"
                    "                'django.template.context_processors.debug',\n"
                    "                'django.template.context_processors.request',\n"
                    "                'django.contrib.auth.context_processors.auth',\n"
                    "                'django.contrib.messages.context_processors.messages',\n"
                    "            ],\n"
                    "        },\n"
                    "    },\n"
                    "]\n\n"
                    "WSGI_APPLICATION = 'core.wsgi.application'\n\n"
                    "DATABASES = {\n"
                    "    'default': {\n"
                    "        'ENGINE': 'django.db.backends.sqlite3',\n"
                    "        'NAME': BASE_DIR / 'db.sqlite3',\n"
                    "    }\n"
                    "}\n\n"
                    "LANGUAGE_CODE = 'en-us'\n"
                    "TIME_ZONE = 'UTC'\n"
                    "USE_I18N = True\n"
                    "USE_TZ = True\n\n"
                    "STATIC_URL = '/static/'\n"
                    "STATIC_ROOT = BASE_DIR / 'staticfiles'\n"
                    "STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []\n\n"
                    "DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'\n"
                )
                zf.writestr("core/__init__.py", "")
                zf.writestr("core/settings.py", settings_py)
                zf.writestr("core/urls.py", (
                    "from django.contrib import admin\n"
                    "from django.urls import path, include\n\n"
                    "urlpatterns = [\n"
                    "    path('admin/', admin.site.urls),\n"
                    "    path('', include('app.urls')),\n"
                    "]\n"
                ))
                zf.writestr("core/wsgi.py", (
                    "import os\n"
                    "from django.core.wsgi import get_wsgi_application\n\n"
                    "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')\n"
                    "application = get_wsgi_application()\n"
                ))
                written_paths.update(["core/__init__.py", "core/settings.py", "core/urls.py", "core/wsgi.py"])

            # Scaffolding app package
            if "app/apps.py" not in written_paths:
                zf.writestr("app/__init__.py", "")
                zf.writestr("app/apps.py", (
                    "from django.apps import AppConfig\n\n"
                    "class AppConfig(AppConfig):\n"
                    "    default_auto_field = 'django.db.models.BigAutoField'\n"
                    "    name = 'app'\n"
                ))
                written_paths.update(["app/__init__.py", "app/apps.py"])

            if "app/models.py" not in written_paths:
                content = models_code or (
                    "from django.db import models\n\n"
                    "class Item(models.Model):\n"
                    "    title = models.CharField(max_length=200)\n"
                    "    created_at = models.DateTimeField(auto_now_add=True)\n"
                )
                zf.writestr("app/models.py", content)
                written_paths.add("app/models.py")

            if "app/views.py" not in written_paths:
                content = views_code or (
                    "from django.shortcuts import render\n\n"
                    "def index(request):\n"
                    "    return render(request, 'index.html')\n"
                )
                zf.writestr("app/views.py", content)
                written_paths.add("app/views.py")

            if "app/admin.py" not in written_paths:
                admin_py = (
                    "from django.contrib import admin\n"
                    "from . import models\n\n"
                    "# Register all models dynamically\n"
                    "for name, obj in models.__dict__.items():\n"
                    "    if isinstance(obj, type) and issubclass(obj, models.models.Model) and obj.__module__ == models.__name__:\n"
                    "        try:\n"
                    "            admin.site.register(obj)\n"
                    "        except Exception:\n"
                    "            pass\n"
                )
                zf.writestr("app/admin.py", admin_py)
                written_paths.add("app/admin.py")

            if "app/urls.py" not in written_paths:
                app_urls = (
                    "from django.urls import path\n"
                    "from . import views\n\n"
                    "urlpatterns = [\n"
                    "    path('', getattr(views, 'index', getattr(views, 'project_list', getattr(views, 'home', list(getattr(views, '__dict__', {}).values())[0] if getattr(views, '__dict__', None) else lambda r: None))), name='index'),\n"
                    "]\n"
                )
                zf.writestr("app/urls.py", app_urls)
                written_paths.add("app/urls.py")

            # Convenience Run Scripts (1-click turnkey startup)
            if "run.sh" not in written_paths:
                run_sh = (
                    "#!/usr/bin/env bash\n"
                    "set -e\n"
                    f"echo '🚀 Starting {display_title}...'\n\n"
                    "# Detect best available Python version with ensurepip support\n"
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
                    "# Clean incomplete venv if activate is missing\n"
                    "if [ -d 'venv' ] && [ ! -f 'venv/bin/activate' ] && [ ! -f 'venv/Scripts/activate' ]; then\n"
                    "    echo 'Detected incomplete virtualenv. Re-creating...'\n"
                    "    rm -rf venv\n"
                    "fi\n\n"
                    "if [ ! -d 'venv' ]; then\n"
                    "    echo \"Creating virtual environment using $PY_BIN...\"\n"
                    "    \"$PY_BIN\" -m venv venv || python3 -m venv venv || python -m venv venv\n"
                    "fi\n\n"
                    "echo 'Activating virtual environment...'\n"
                    "source venv/bin/activate\n\n"
                    "echo 'Installing dependencies...'\n"
                    "pip install -r requirements.txt\n\n"
                    "echo 'Applying database migrations...'\n"
                    "python manage.py makemigrations app || true\n"
                    "python manage.py migrate\n\n"
                    "echo 'Starting server at http://127.0.0.1:8000/ ...'\n"
                    "python manage.py runserver 127.0.0.1:8000\n"
                )
                sh_info = zipfile.ZipInfo("run.sh")
                sh_info.external_attr = 0o755 << 16
                zf.writestr(sh_info, run_sh)
                written_paths.add("run.sh")

            if "run.py" not in written_paths:
                run_py = (
                    "#!/usr/bin/env python3\n"
                    '"""Turnkey 1-Click Launcher for DevDialogue AI Generated Project."""\n'
                    "import os, sys, subprocess, shutil\n"
                    "from pathlib import Path\n\n"
                    "BASE_DIR = Path(__file__).resolve().parent\n"
                    "VENV_DIR = BASE_DIR / 'venv'\n"
                    "IS_WIN = sys.platform == 'win32'\n"
                    "VENV_PY = VENV_DIR / ('Scripts/python.exe' if IS_WIN else 'bin/python')\n"
                    "VENV_PIP = VENV_DIR / ('Scripts/pip.exe' if IS_WIN else 'bin/pip')\n"
                    "ACTIVATE = VENV_DIR / ('Scripts/activate.bat' if IS_WIN else 'bin/activate')\n\n"
                    "def main():\n"
                    f"    print('🚀 Starting {display_title}...')\n"
                    "    if VENV_DIR.exists() and not ACTIVATE.exists():\n"
                    "        print('Cleaning broken virtualenv...')\n"
                    "        shutil.rmtree(VENV_DIR, ignore_errors=True)\n"
                    "    if not VENV_PY.exists():\n"
                    "        print('Creating virtual environment...')\n"
                    "        py_cand = sys.executable\n"
                    "        for c in ['python3.13', 'python3.12', 'python3.11', 'python3']:\n"
                    "            if shutil.which(c):\n"
                    "                try:\n"
                    "                    subprocess.check_call([c, '-c', 'import ensurepip'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                    "                    py_cand = c\n"
                    "                    break\n"
                    "                except Exception:\n"
                    "                    pass\n"
                    "        subprocess.check_call([py_cand, '-m', 'venv', str(VENV_DIR)])\n"
                    "    reqs = BASE_DIR / 'requirements.txt'\n"
                    "    if reqs.exists():\n"
                    "        print('Installing dependencies...')\n"
                    "        subprocess.check_call([str(VENV_PIP), 'install', '-r', str(reqs)])\n"
                    "    print('Applying database migrations...')\n"
                    "    subprocess.call([str(VENV_PY), 'manage.py', 'makemigrations', 'app'])\n"
                    "    subprocess.check_call([str(VENV_PY), 'manage.py', 'migrate'])\n"
                    "    print('\\n============================================================')\n"
                    "    print('🌐 Application running at: http://127.0.0.1:8000/')\n"
                    "    print('============================================================\\n')\n"
                    "    subprocess.call([str(VENV_PY), 'manage.py', 'runserver', '127.0.0.1:8000'])\n\n"
                    "if __name__ == '__main__':\n"
                    "    main()\n"
                )
                py_info = zipfile.ZipInfo("run.py")
                py_info.external_attr = 0o755 << 16
                zf.writestr(py_info, run_py)
                written_paths.add("run.py")

            if "run.bat" not in written_paths:
                run_bat = (
                    "@echo off\n"
                    f"echo Starting {display_title}...\n"
                    "if not exist venv (\n"
                    "    echo Creating virtual environment...\n"
                    "    python -m venv venv\n"
                    ")\n"
                    "call venv\\Scripts\\activate.bat\n"
                    "echo Installing dependencies...\n"
                    "pip install -r requirements.txt\n"
                    "echo Applying migrations...\n"
                    "python manage.py makemigrations app\n"
                    "python manage.py migrate\n"
                    "echo Starting server at http://127.0.0.1:8000/ ...\n"
                    "python manage.py runserver 127.0.0.1:8000\n"
                    "pause\n"
                )
                zf.writestr("run.bat", run_bat)
                written_paths.add("run.bat")

            if ".gitignore" not in written_paths:
                zf.writestr(".gitignore", "venv/\n__pycache__/\n*.py[cod]\ndb.sqlite3\n*.log\n.DS_Store\n")
                written_paths.add(".gitignore")

            # 4. Turnkey README.md
            if "README.md" not in written_paths:
                readme_content = (
                    f"# {display_title}\n\n"
                    f"Generated by **DevDialogue AI** on {session.started_at.strftime('%Y-%m-%d %H:%M:%S')}.\n\n"
                    "This is a complete, turnkey Django web application configured and ready to run in any IDE (VS Code, PyCharm, Sublime) or terminal.\n\n"
                    "---\n\n"
                    "## ⚡ Quick Start (1-Click Run)\n\n"
                    "- **Linux / macOS**:\n"
                    "  ```bash\n"
                    "  ./run.sh\n"
                    "  ```\n"
                    "- **Windows**:\n"
                    "  Double-click `run.bat` or run in CMD:\n"
                    "  ```cmd\n"
                    "  run.bat\n"
                    "  ```\n\n"
                    "---\n\n"
                    "## 🛠️ Manual Setup in Any IDE\n\n"
                    "1. **Open the extracted project folder** in your IDE (VS Code, PyCharm, Cursor).\n"
                    "2. **Create and activate a virtual environment**:\n"
                    "   ```bash\n"
                    "   python3 -m venv venv\n"
                    "   source venv/bin/activate       # On Windows: venv\\Scripts\\activate\n"
                    "   ```\n"
                    "3. **Install dependencies**:\n"
                    "   ```bash\n"
                    "   pip install -r requirements.txt\n"
                    "   ```\n"
                    "4. **Apply database migrations**:\n"
                    "   ```bash\n"
                    "   python manage.py makemigrations app\n"
                    "   python manage.py migrate\n"
                    "   ```\n"
                    "5. **(Optional) Create Admin User**:\n"
                    "   ```bash\n"
                    "   python manage.py createsuperuser\n"
                    "   ```\n"
                    "6. **Start the development server**:\n"
                    "   ```bash\n"
                    "   python manage.py runserver\n"
                    "   ```\n"
                    "7. Open **`http://127.0.0.1:8000/`** in your browser!\n\n"
                    "---\n\n"
                    "## 📂 Included Project Files\n" +
                    "\n".join([f"- `{p}`" for p in sorted(written_paths)])
                )
                zf.writestr("README.md", readme_content)

            # Include VERIFICATION.md summarizing latest verification run
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
