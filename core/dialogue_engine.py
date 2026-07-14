import re
from django.utils import timezone
from core.models import Message, GeneratedCode

class DialogueEngine:
    QUESTIONS = [
        # (index, question_text, key_saved)
        (0, "Welcome! I've received your initial project description. Let's refine the requirements before we write the code.\n\nFirst, what is your preferred tech stack for this project? (e.g., Python/Django, Node.js/React, HTML/CSS/JS, SQLite, PostgreSQL, etc.)", "tech_stack"),
        (1, "Got it. Next, let's identify the core modules or features. Can you list the main features/modules you want to include in this system?", "features"),
        (2, "Understood. What user roles or authentication mechanisms (e.g., standard login/signup, OTP, admin roles) do you require?", "auth"),
        (3, "Excellent. Lastly, are there any specific external APIs, database constraints, or edge cases/error handling I should keep in mind?", "constraints"),
    ]

    @classmethod
    def process_message(cls, session, user_content):
        # Save user message
        Message.objects.create(session=session, role='user', content=user_content)
        
        # Load conversation history (excluding the user message just saved to count previously)
        messages = list(session.messages.all())
        user_msgs = [m for m in messages if m.role == 'user']
        assist_msgs = [m for m in messages if m.role == 'assistant']
        
        # Step 0: Initial prompt is already user_msgs[0]
        # We check how many questions have been asked
        asked_count = len(assist_msgs)

        if asked_count < len(cls.QUESTIONS):
            # Ask next question
            next_q = cls.QUESTIONS[asked_count][1]
            Message.objects.create(session=session, role='assistant', content=next_q)
            return next_q

        elif asked_count == len(cls.QUESTIONS):
            # Generate summary and ask for confirmation
            tech_stack = user_msgs[1].content if len(user_msgs) > 1 else "Not specified"
            features = user_msgs[2].content if len(user_msgs) > 2 else "Not specified"
            auth = user_msgs[3].content if len(user_msgs) > 3 else "Not specified"
            constraints = user_msgs[4].content if len(user_msgs) > 4 else "Not specified"
            
            summary = (
                "### Project Requirements Summary\n\n"
                f"- **Project Concept**: {user_msgs[0].content}\n"
                f"- **Tech Stack**: {tech_stack}\n"
                f"- **Core Modules**: {features}\n"
                f"- **Authentication**: {auth}\n"
                f"- **Constraints/APIs**: {constraints}\n\n"
                "I have compiled all the requirements. Should I proceed to generate the codebase?"
            )
            if session.mode == 'mode2':
                summary += " (We will generate this incrementally, module-by-module)."
                
            Message.objects.create(session=session, role='assistant', content=summary)
            return summary

        # If they are confirming the generation
        confirmation_msg = user_msgs[-1].content.lower().strip()
        
        if session.mode == 'mode1':
            # Mode 1: Full generation
            if session.status == 'active':
                if 'yes' in confirmation_msg or 'y' == confirmation_msg or 'proceed' in confirmation_msg or 'generate' in confirmation_msg:
                    session.status = 'completed'
                    session.save()
                    
                    # Generate full codebase
                    cls.generate_code_files(session)
                    
                    response = (
                        "### 🎉 Codebase Generated Successfully!\n\n"
                        "I have generated the full codebase based on your requirements. You can inspect the code in the sidebar panel on the right. "
                        "The generated modules include:\n"
                        "1. `models.py` (Database schemas & relationships)\n"
                        "2. `views.py` (Business logic and actions)\n"
                        "3. `templates/index.html` (Responsive frontend interface)\n\n"
                        "You can download individual modules or the entire codebase. Let me know if you need any adjustments!"
                    )
                    Message.objects.create(session=session, role='assistant', content=response)
                    return response
                else:
                    response = "Would you like me to make any changes to the requirements first, or shall we proceed with code generation? (Say 'yes' to generate, or describe the changes)."
                    Message.objects.create(session=session, role='assistant', content=response)
                    return response
            else:
                response = "The codebase for this session has already been generated. Let me know if you need to start a new project!"
                Message.objects.create(session=session, role='assistant', content=response)
                return response
                
        else:
            # Mode 2: Incremental Generation
            # Let's count how many modules have been generated
            generated_modules = list(session.generated_codes.all())
            modules_list = ["models.py", "views.py", "templates/index.html"]
            
            if len(generated_modules) < len(modules_list):
                current_module = modules_list[len(generated_modules)]
                
                # Check if they approved the previous module (if there is one)
                if len(generated_modules) > 0:
                    last_user_approval = confirmation_msg
                    if not ('yes' in last_user_approval or 'approve' in last_user_approval or 'ok' in last_user_approval or 'next' in last_user_approval or 'y' == last_user_approval):
                        # User wants modifications to the last module
                        response = (
                            f"Got it! I will modify `{generated_modules[-1].module_name}` based on your feedback: *\"{user_msgs[-1].content}\"*.\n\n"
                            "Here is the updated code:\n"
                        )
                        # We just regenerate/update the last module
                        last_mod = generated_modules[-1]
                        last_mod.code_content = cls.get_mock_code(last_mod.module_name, f"Modified based on: {user_msgs[-1].content}")
                        last_mod.save()
                        
                        response += f"```python\n# Updated {last_mod.module_name}\n" + last_mod.code_content + "\n```\n\n"
                        response += f"Do you approve this updated `{last_mod.module_name}`? (Yes to approve and proceed, or specify further changes)."
                        Message.objects.create(session=session, role='assistant', content=response)
                        return response
                
                # Generate the next module
                code = cls.get_mock_code(current_module)
                GeneratedCode.objects.create(session=session, module_name=current_module, code_content=code)
                
                response = (
                    f"### Module {len(generated_modules)+1}/{len(modules_list)}: `{current_module}`\n\n"
                    f"I have generated the code for `{current_module}`. You can see it in the right panel.\n\n"
                    f"Do you approve this module? (Say **yes** to approve and move to the next, or describe what changes you want)."
                )
                Message.objects.create(session=session, role='assistant', content=response)
                return response
            else:
                # All modules completed
                if session.status == 'active':
                    session.status = 'completed'
                    session.save()
                response = (
                    "### 🚀 Incremental Generation Complete!\n\n"
                    "All modules (`models.py`, `views.py`, `templates/index.html`) have been approved and generated. "
                    "You can view and download all files from the sidebar. Thank you for using DevDialogue AI!"
                )
                Message.objects.create(session=session, role='assistant', content=response)
                return response

    @classmethod
    def generate_code_files(cls, session):
        # Generate all mock code files
        modules = ["models.py", "views.py", "templates/index.html"]
        for mod in modules:
            if not session.generated_codes.filter(module_name=mod).exists():
                code = cls.get_mock_code(mod)
                GeneratedCode.objects.create(session=session, module_name=mod, code_content=code)

    @classmethod
    def get_mock_code(cls, module_name, modifications=""):
        mod_comment = f"# {modifications}\n" if modifications else ""
        if module_name == "models.py":
            return mod_comment + (
                "from django.db import models\n"
                "from django.contrib.auth.models import User\n\n"
                "class Project(models.Model):\n"
                "    name = models.CharField(max_length=200)\n"
                "    description = models.TextField()\n"
                "    created_at = models.DateTimeField(auto_now_add=True)\n"
                "    owner = models.ForeignKey(User, on_delete=models.CASCADE)\n\n"
                "    def __str__(self):\n"
                "        return self.name\n\n"
                "class Task(models.Model):\n"
                "    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')\n"
                "    title = models.CharField(max_length=200)\n"
                "    is_completed = models.BooleanField(default=False)\n"
                "    due_date = models.DateField(null=True, blank=True)\n\n"
                "    def __str__(self):\n"
                "        return self.title\n"
            )
        elif module_name == "views.py":
            return mod_comment + (
                "from django.shortcuts import render, get_object_or_404, redirect\n"
                "from django.contrib.auth.decorators import login_required\n"
                "from .models import Project, Task\n\n"
                "@login_required\n"
                "def project_list(request):\n"
                "    projects = Project.objects.filter(owner=request.user)\n"
                "    return render(request, 'projects/list.html', {'projects': projects})\n\n"
                "@login_required\n"
                "def project_detail(request, pk):\n"
                "    project = get_object_or_404(Project, pk=pk, owner=request.user)\n"
                "    tasks = project.tasks.all()\n"
                "    return render(request, 'projects/detail.html', {'project': project, 'tasks': tasks})\n\n"
                "@login_required\n"
                "def create_project(request):\n"
                "    if request.method == 'POST':\n"
                "        name = request.POST.get('name')\n"
                "        desc = request.POST.get('description')\n"
                "        Project.objects.create(name=name, description=desc, owner=request.user)\n"
                "        return redirect('project_list')\n"
                "    return render(request, 'projects/create.html')\n"
            )
        elif module_name == "templates/index.html":
            return mod_comment + (
                "<!DOCTYPE html>\n"
                "<html lang=\"en\">\n"
                "<head>\n"
                "    <meta charset=\"UTF-8\">\n"
                "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=initial-scale=1.0\">\n"
                "    <title>My Generated App</title>\n"
                "    <style>\n"
                "        body { font-family: sans-serif; background-color: #f4f7f6; color: #333; margin: 0; padding: 40px; }\n"
                "        .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }\n"
                "        h1 { color: #2c3e50; border-bottom: 2px solid #ecf0f1; padding-bottom: 10px; }\n"
                "        .task-list { list-style: none; padding: 0; }\n"
                "        .task-item { padding: 12px; border-bottom: 1px solid #eee; display: flex; align-items: center; justify-content: space-between; }\n"
                "        .completed { text-decoration: line-through; color: #95a5a6; }\n"
                "        .btn { display: inline-block; padding: 8px 16px; background: #3498db; color: white; text-decoration: none; border-radius: 4px; }\n"
                "    </style>\n"
                "</head>\n"
                "<body>\n"
                "    <div class=\"container\">\n"
                "        <h1>Active Projects</h1>\n"
                "        <p>Welcome to your generated task tracking application!</p>\n"
                "        <a href=\"#\" class=\"btn\">Create New Project</a>\n"
                "    </div>\n"
                "</body>\n"
                "</html>\n"
            )
        return "# Unknown module code"
