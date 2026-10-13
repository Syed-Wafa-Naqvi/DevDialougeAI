import re

class MockProvider:
    """
    Deterministic Mock LLM Provider for unit testing and offline development.
    Guarantees 0 external network calls.
    """
    def __init__(self, provider_name: str = "mock", model_name: str = "mock-v1"):
        self.provider_name = provider_name
        self.model_name = model_name
        self.scripted_responses = []

    def is_available(self) -> bool:
        return True

    def queue_response(self, response_text: str):
        """Allows test cases to queue specific scripted responses."""
        self.scripted_responses.append(response_text)

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        if self.scripted_responses:
            return self.scripted_responses.pop(0)

        prompt_lower = prompt.lower()
        sys_lower = (system_prompt or "").lower()

        # Completeness scoring query
        if "completeness" in prompt_lower or "completeness" in sys_lower or "rubric" in prompt_lower:
            if any(k in prompt_lower for k in ["summary", "proceed", "ready", "generate", "build code", "compile"]):
                return '''{
                  "categories": {
                    "purpose_and_users": "covered",
                    "core_features": "covered",
                    "data_model": "covered",
                    "auth_and_roles": "covered",
                    "tech_stack": "covered",
                    "integrations": "covered",
                    "non_functional": "covered",
                    "deployment": "covered"
                  },
                  "next_questions": [],
                  "contradictions": []
                }'''
            return '''{
              "categories": {
                "purpose_and_users": "covered",
                "core_features": "partial",
                "data_model": "missing",
                "auth_and_roles": "missing",
                "tech_stack": "covered",
                "integrations": "missing",
                "non_functional": "missing",
                "deployment": "missing"
              },
              "next_questions": ["What database schema or authentication do you prefer?"],
              "contradictions": []
            }'''

        # Repair query matching
        if "repair" in prompt_lower or "repair" in sys_lower:
            if "bad_syntax.py" in prompt_lower:
                return '''{
                  "summary": "Fixed bad syntax in bad_syntax.py",
                  "operations": [
                    {"op": "replace_in_file", "path": "bad_syntax.py", "old": "def foo(:", "new": "def foo():"}
                  ]
                }'''
            return '''{
              "summary": "Applied syntax repair",
              "operations": [
                {"op": "replace_in_file", "path": "todo/views.py", "old": "def foo(:", "new": "def foo():"}
              ]
            }'''

        # Plan generation query
        if "architecture plan" in prompt_lower or "project plan" in prompt_lower or "generate the complete multi-file project architecture plan" in prompt_lower or "json project plan" in sys_lower:
            return '''{
              "project_name": "mock_app",
              "stack": {"language": "python", "framework": "django", "database": "sqlite", "other": []},
              "files": [
                {
                  "path": "todo/models.py",
                  "purpose": "Task model",
                  "depends_on": [],
                  "exports": [{"name": "Task", "kind": "class", "signature": "Task(models.Model)"}]
                },
                {
                  "path": "todo/views.py",
                  "purpose": "Task views",
                  "depends_on": ["todo/models.py"],
                  "exports": [{"name": "task_list", "kind": "function", "signature": "task_list(request)"}]
                }
              ],
              "dependencies": ["django>=5.0"],
              "entry_points": ["manage.py"],
              "check_commands": ["python manage.py check"],
              "test_commands": ["python manage.py test"],
              "assumptions": ["Default SQLite DB"]
            }'''

        # Ambiguity check (only when explicitly running ambiguity detection, not in interview chats)
        if "ambiguity" in sys_lower or "analyze this conversation for conflicting requirements" in prompt_lower:
            return "NO_AMBIGUITY"

        # Code generation query (only triggered for actual code generator queries, not conversation history)
        is_code_gen = (
            "generate high-quality, production-ready source code" in prompt_lower
            or "provide only the actual executable source code" in prompt_lower
            or sys_lower == "code generator"
            or (prompt_lower.startswith("generate code for") or prompt_lower.startswith("write code for"))
        )
        if is_code_gen:
            if "models.py" in prompt_lower:
                return (
                    "from django.db import models\n"
                    "from django.contrib.auth.models import User\n\n"
                    "class Project(models.Model):\n"
                    "    name = models.CharField(max_length=200)\n"
                    "    description = models.TextField()\n"
                    "    created_at = models.DateTimeField(auto_now_add=True)\n"
                    "    owner = models.ForeignKey(User, on_delete=models.CASCADE)\n\n"
                    "    def __str__(self):\n"
                    "        return self.name\n"
                )
            elif "views.py" in prompt_lower:
                return (
                    "from django.shortcuts import render, get_object_or_404\n"
                    "from django.contrib.auth.decorators import login_required\n"
                    "from .models import Project\n\n"
                    "@login_required\n"
                    "def project_list(request):\n"
                    "    projects = Project.objects.filter(owner=request.user)\n"
                    "    return render(request, 'projects/list.html', {'projects': projects})\n"
                )
            elif "index.html" in prompt_lower:
                return (
                    "<!DOCTYPE html>\n"
                    "<html><head><title>Mock Web App</title></head>\n"
                    "<body><h1>Mock Web Application</h1></body></html>\n"
                )
            return "# Mock generated module code\n"

        # SRS Requirements synthesis query
        if "requirements" in prompt_lower or "synthesize" in prompt_lower or "srs" in sys_lower:
            return (
                "### Project Requirements Summary\n\n"
                "- **Project Concept**: Mock Software Application\n"
                "- **Tech Stack**: Python (Django), SQLite\n"
                "- **Core Modules**: Authentication, Task Management\n"
                "- **Authentication & Security**: Email OTP Login\n"
                "- **Constraints & External APIs**: Standard REST Architecture\n\n"
                "I have compiled all the requirements. Should I proceed to generate the codebase?"
            )

        # Meta questions / greetings
        if any(k in prompt_lower for k in ["who are you", "what is this", "who is this", "what can you do"]):
            return (
                "Hello! I am DevDialogue AI — your Senior Software Architect. "
                "I help turn your project ideas into production-ready software codebases. "
                "What software application or system are you planning to build today?"
            )

        # Interview questions simulation
        if any(k in prompt_lower for k in ["interview", "question", "elicit", "requirement"]) or "software architect" in sys_lower:
            # Check latest user message for direct confusion or questions
            latest_user = ""
            if "latest user input:" in prompt_lower:
                try:
                    latest_user = prompt_lower.split("latest user input:")[1].split("\n")[0].strip().strip('"\'')
                except Exception:
                    pass

            if any(w in latest_user for w in ["?", "lost", "confused", "who are you", "what are you"]):
                if any(w in latest_user for w in ["lost", "confused", "??", "what", "where"]):
                    return "I'm right here with you! We are specifying your software application step by step. What tech stack or main feature would you like to build?"

            if "stack" not in prompt_lower and "framework" not in prompt_lower:
                return "Great concept! What is your preferred tech stack (e.g., Python/Django, Node.js/React, FastAPI, SQLite, PostgreSQL)?"
            elif "module" not in prompt_lower and "feature" not in prompt_lower:
                return "Got it. What are the primary features or modules you want to include in this system?"
            elif "auth" not in prompt_lower and "login" not in prompt_lower:
                return "Understood. What user roles or authentication mechanisms (e.g., standard login, OTP, JWT, Admin) do you require?"
            elif "database" not in prompt_lower and "storage" not in prompt_lower:
                return "What database or storage solution would you like to use (e.g., PostgreSQL, SQLite, MongoDB, Redis)?"
            elif "api" not in prompt_lower and "integration" not in prompt_lower:
                return "Are there any specific third-party APIs, external integrations, or background worker tasks needed?"
            else:
                return "We have defined the core technical architecture! Would you like me to synthesize the full specification summary and proceed to generation?"

        # Default professional guidance response
        return "I am ready to help build your system. Could you share a brief overview of your software project idea?"
