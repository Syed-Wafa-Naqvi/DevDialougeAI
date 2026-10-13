import re
from graphlib import TopologicalSorter, CycleError
from generator.path_safety import PathSafetyManager, PathSafetyError

class PlanValidationError(ValueError):
    """Raised when a ProjectPlan JSON fails architectural contract validation."""
    pass

class PlanValidator:
    ALLOWED_COMMAND_PATTERNS = [
        r'^python\s+manage\.py\s+check.*$',
        r'^python\s+manage\.py\s+test.*$',
        r'^python\s+-m\s+pytest.*$',
        r'^python\s+-m\s+py_compile.*$',
        r'^pytest.*$',
        r'^npm\s+test.*$',
        r'^python\s+manage\.py\s+makemigrations\s+--check.*$',
    ]

    @classmethod
    def is_command_allowed(cls, cmd: str) -> bool:
        if not cmd or not isinstance(cmd, str):
            return False
        cmd_clean = cmd.strip()
        return any(re.match(pattern, cmd_clean) for pattern in cls.ALLOWED_COMMAND_PATTERNS)

    @classmethod
    def validate_and_sort_plan(cls, plan_data: dict) -> dict:
        """
        Validates the project plan dictionary and returns a dict containing:
        - 'clean_plan': normalized, sanitized plan data dict
        - 'generation_order': topologically sorted list of file paths
        Raises PlanValidationError if validation fails.
        """
        if not isinstance(plan_data, dict):
            raise PlanValidationError("Plan must be a JSON object.")

        files = plan_data.get('files')
        if not isinstance(files, list) or not files:
            raise PlanValidationError("Plan must contain a non-empty 'files' array.")

        PathSafetyManager.validate_project_file_count(len(files))

        path_to_file = {}
        dependency_graph = {}
        errors = []

        # 1. Validate file paths & exports
        for idx, file_info in enumerate(files):
            if not isinstance(file_info, dict):
                errors.append(f"File #{idx+1}: must be a JSON object.")
                continue

            raw_path = file_info.get('path')
            try:
                clean_path = PathSafetyManager.validate_path(raw_path)
            except PathSafetyError as e:
                errors.append(f"File #{idx+1} ({raw_path}): {str(e)}")
                continue

            if clean_path in path_to_file:
                errors.append(f"Duplicate file path in plan: '{clean_path}'")
                continue

            # Validate exports uniqueness
            exports = file_info.get('exports', [])
            export_names = set()
            for exp in exports:
                if isinstance(exp, dict) and 'name' in exp:
                    name = exp['name']
                    if name in export_names:
                        errors.append(f"File '{clean_path}': duplicate export name '{name}'.")
                    export_names.add(name)

            file_info['path'] = clean_path
            path_to_file[clean_path] = file_info

        if errors:
            raise PlanValidationError("Plan validation failed:\n" + "\n".join(errors))

        # 2. Validate dependencies existence & build graph
        for clean_path, file_info in path_to_file.items():
            deps = file_info.get('depends_on', [])
            clean_deps = []
            for dep in deps:
                try:
                    clean_dep = PathSafetyManager.validate_path(dep)
                except PathSafetyError as e:
                    errors.append(f"File '{clean_path}' dependency '{dep}': {str(e)}")
                    continue

                if clean_dep not in path_to_file:
                    errors.append(f"File '{clean_path}' depends on '{clean_dep}', which is not defined in the plan.")
                else:
                    clean_deps.append(clean_dep)

            file_info['depends_on'] = clean_deps
            dependency_graph[clean_path] = set(clean_deps)

        if errors:
            raise PlanValidationError("Dependency validation failed:\n" + "\n".join(errors))

        # 3. Topological Sort (Cycle Detection)
        try:
            sorter = TopologicalSorter(dependency_graph)
            generation_order = list(sorter.static_order())
        except CycleError as e:
            cycle_nodes = " -> ".join(str(node) for node in e.args[1]) if len(e.args) > 1 else str(e)
            raise PlanValidationError(f"Dependency cycle detected in plan files: {cycle_nodes}")

        # 4. Filter check/test commands against allowlist
        check_cmds = [cmd for cmd in plan_data.get('check_commands', []) if cls.is_command_allowed(cmd)]
        test_cmds = [cmd for cmd in plan_data.get('test_commands', []) if cls.is_command_allowed(cmd)]

        plan_data['check_commands'] = check_cmds
        plan_data['test_commands'] = test_cmds

        return {
            'clean_plan': plan_data,
            'generation_order': generation_order
        }

class PlanGenerator:
    SYSTEM_PROMPT = (
        "You are an expert software architect. Analyze the SRS requirements summary and generate a strict JSON project plan.\n"
        "Schema:\n"
        "{\n"
        '  "project_name": "app_name",\n'
        '  "stack": {"language": "python", "framework": "django", "database": "sqlite", "other": []},\n'
        '  "files": [\n'
        '    {\n'
        '      "path": "todo/models.py",\n'
        '      "purpose": "Task model definition",\n'
        '      "depends_on": [],\n'
        '      "exports": [{"name": "Task", "kind": "class", "signature": "Task(models.Model)"}]\n'
        '    }\n'
        '  ],\n'
        '  "dependencies": ["django>=5.0"],\n'
        '  "entry_points": ["manage.py"],\n'
        '  "check_commands": ["python manage.py check"],\n'
        '  "test_commands": ["python manage.py test"],\n'
        '  "assumptions": ["Standard SQLite database"]\n'
        "}\n"
        "Return ONLY valid JSON."
    )

    @classmethod
    def generate_plan(cls, srs_summary: str, session, provider_name: str = None) -> 'ProjectPlan':
        from llm_engine.router import LLMRouter
        from chat.models import ProjectPlan
        from generator.protocol import EditProtocolEngine

        prompt = f"SRS Requirements Summary:\n{srs_summary}\n\nGenerate the complete multi-file project architecture plan in JSON format."

        attempts = 0
        last_error = ""

        while attempts < 3:
            attempts += 1
            curr_prompt = prompt if attempts == 1 else f"{prompt}\n\nPREVIOUS PLAN ATTEMPT FAILED VALIDATION:\n{last_error}\nFix the JSON plan to be valid."

            raw_resp = LLMRouter.generate(
                prompt=curr_prompt,
                system_prompt=cls.SYSTEM_PROMPT,
                provider_name=provider_name,
                purpose='plan',
                session=session
            )

            try:
                plan_data = EditProtocolEngine.parse_payload(raw_resp)
                result = PlanValidator.validate_and_sort_plan(plan_data)
                clean_plan = result['clean_plan']
                gen_order = result['generation_order']

                latest_plan = session.plans.order_by('-version').first()
                new_version = (latest_plan.version + 1) if latest_plan else 1

                # Mark previous plans as superseded
                session.plans.filter(status='draft').update(status='superseded')

                project_plan = ProjectPlan.objects.create(
                    session=session,
                    plan_data=clean_plan,
                    generation_order=gen_order,
                    version=new_version,
                    status='draft'
                )
                return project_plan
            except Exception as e:
                last_error = str(e)

        raise PlanValidationError(f"Failed to generate a valid project plan after 3 attempts. Last error: {last_error}")

