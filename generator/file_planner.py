import json
import re

class FilePlanner:
    @classmethod
    def get_module_list(cls, tech_stack: str = "django", provider_name: str = None) -> list:
        ts_lower = tech_stack.lower()

        # If a full requirements summary was passed, attempt dynamic LLM planning if available
        if len(tech_stack) > 50 and tech_stack.strip().lower() not in ("django", "flutter", "fastapi", "flask", "go", "rust"):
            try:
                from llm_engine.router import LLMRouter
                prompt = (
                    "Plan the necessary source code and configuration files for this software project.\n\n"
                    f"PROJECT SPECIFICATION:\n{tech_stack}\n\n"
                    "INSTRUCTIONS:\n"
                    "Return ONLY a JSON array of relative file paths (e.g. [\"pubspec.yaml\", \"lib/main.dart\", ...]). "
                    "Do NOT return markdown or explanation, just the JSON array."
                )
                system_prompt = "You are an automated file structure planner. Output a valid JSON array of relative file paths."
                resp = LLMRouter.generate(prompt=prompt, system_prompt=system_prompt, provider_name=provider_name)
                match = re.search(r'\[\s*".*?"\s*\]', resp, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, list) and len(parsed) >= 2:
                        cleaned = [p.strip().lstrip('/') for p in parsed if isinstance(p, str) and '.' in p and not p.endswith(('.png', '.jpg', '.ico'))]
                        if len(cleaned) >= 2:
                            return cleaned
            except Exception:
                pass

        # Domain-aware contextual fallbacks
        if "flutter" in ts_lower or "dart" in ts_lower:
            if "snake" in ts_lower or "game" in ts_lower:
                return [
                    "pubspec.yaml",
                    "lib/main.dart",
                    "lib/models/point.dart",
                    "lib/providers/game_provider.dart",
                    "lib/screens/game_screen.dart",
                    "test/widget_test.dart"
                ]
            return [
                "pubspec.yaml",
                "lib/main.dart",
                "lib/models/task.dart",
                "lib/screens/home_screen.dart",
                "lib/widgets/task_tile.dart",
                "test/widget_test.dart"
            ]
        elif "go" in ts_lower or "golang" in ts_lower:
            return ["go.mod", "main.go", "handlers/api.go", "models/data.go"]
        elif "rust" in ts_lower:
            return ["Cargo.toml", "src/main.rs", "src/models.rs"]
        elif "fastapi" in ts_lower:
            return ["main.py", "models.py", "schemas.py", "database.py"]
        elif "express" in ts_lower or "node" in ts_lower or "react" in ts_lower:
            return ["server.js", "models/User.js", "routes/api.js", "public/index.html"]
        elif "flask" in ts_lower:
            return ["app.py", "models.py", "templates/index.html"]
        elif "java" in ts_lower or "spring" in ts_lower:
            return ["pom.xml", "src/main/java/com/app/Application.java", "src/main/java/com/app/controller/ApiController.java"]
        else:
            # Default Django stack
            return ["models.py", "views.py", "templates/index.html"]


