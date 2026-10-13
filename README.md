# DevDialogue AI

An interactive, conversation-driven specification elicitation and codebase generation engine designed to eliminate prompt ambiguity in software prototyping.

---

## 🚀 Key Features & Capabilities

- **Enterprise Multi-App Architecture**: Decoupled, domain-driven Django applications (`accounts/`, `llm_engine/`, `dialogue/`, `generator/`, `chat/`, `exporter/`).
- **Multi-Model AI Engine**: Support for **Free AI (LLaMA 3.3 / Qwen)** out-of-the-box + **Google Gemini**, **OpenAI (GPT-4o)**, **Claude 3.5**, and **DeepSeek API** via `.env` keys.
- **Dynamic Elicitation & Dialogue Engine (Mode 1)**: Live AI-driven interviewing that adapts to developer inputs, detects conflicting constraints, calculates readiness completeness (0-100%), and synthesizes formal SRS summaries.
- **Incremental Code Generation (Mode 2)**: Module-by-module generation with live developer feedback & module modification loops before advancing.
- **Multi-Stack Code Generation**: Generates full production code across Python/Django, FastAPI, Node.js/Express/React, and Flask.
- **One-Click Project ZIP Export**: In-memory `.zip` project packager containing all generated modules and a project `README.md`.
- **Prism.js Syntax Highlighting**: Professional syntax highlighting for Python, HTML, JavaScript, CSS, and JSON in the split-screen code console.
- **Secure OTP Verification**: Email verification with a dynamic 2-minute countdown timer and admin overrides.

---

## 🏗️ Architecture & App Structure

```
DevDialougeAI/
├── accounts/          # User authentication, OTP verification, profiles, settings
├── llm_engine/        # Multi-model AI router (Free AI, Gemini, GPT-4o, Claude, DeepSeek)
├── dialogue/          # Requirement elicitation, ambiguity detection, completeness scoring
├── generator/         # Multi-stack file tree planner & code generator
├── chat/              # Chat sessions, interactive messaging, split-screen UI
├── exporter/          # In-memory ZIP archiver & download API
├── core/              # Templates, CSS styling & static assets
├── config/            # Root Django project settings & URL dispatcher
└── manage.py
```

---

## 🛠️ Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Syed-Wafa-Naqvi/DevDialougeAI.git
   cd DevDialougeAI
   ```

2. **Set up a virtual environment**:
   ```bash
   python3 -m venv env
   source env/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run migrations**:
   ```bash
   python manage.py migrate
   ```

5. **Run the test suite**:
   ```bash
   python manage.py test
   ```

6. **Start the development server**:
   ```bash
   python manage.py runserver
   ```

---

## ⚡ Lite Runtime Checks (Optional & Feature-Flagged)

DevDialogue AI includes an optional **Lite Runtime Verification Engine** (`generator/runtime_verifier.py`) that runs execution checks (`compileall`, `manage.py check`, `pytest`/`unittest`) on generated code.

> **⚠️ Security & Isolation Notice**:
> Lite Runtime Checks execute generated Python code using system subprocesses with environment stripping and `resource.setrlimit` constraints (CPU time, memory caps, file size limits). This mode **does not provide full container isolation** (no Docker).
> - Restricted exclusively to **staff/admin users** when `RUNTIME_CHECKS_ENABLED=True`.
> - Only enable on server environments where subprocess execution risk is acceptable.

### Configuration (`.env`)
```env
RUNTIME_CHECKS_ENABLED=False
RUNTIME_CHECKS_TIMEOUT=60
RUNTIME_CHECKS_VENV_PATH=/path/to/venv/bin/python
```

