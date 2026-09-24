class FilePlanner:
    @classmethod
    def get_module_list(cls, tech_stack: str = "django") -> list:
        ts_lower = tech_stack.lower()
        if "fastapi" in ts_lower:
            return ["main.py", "models.py", "schemas.py", "database.py"]
        elif "express" in ts_lower or "node" in ts_lower or "react" in ts_lower:
            return ["server.js", "models/User.js", "routes/api.js", "public/index.html"]
        elif "flask" in ts_lower:
            return ["app.py", "models.py", "templates/index.html"]
        else:
            # Default Django stack
            return ["models.py", "views.py", "templates/index.html"]
