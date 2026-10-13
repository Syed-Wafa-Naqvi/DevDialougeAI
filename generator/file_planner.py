class FilePlanner:
    @classmethod
    def get_module_list(cls, tech_stack: str = "django") -> list:
        ts_lower = tech_stack.lower()
        if "flutter" in ts_lower or "dart" in ts_lower:
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

