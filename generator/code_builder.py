import ast
import re
from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class CodeBuilder:
    @classmethod
    def _extract_dart_signatures(cls, content: str) -> list:
        lines = []
        # 1. Enums
        for m in re.finditer(r'enum\s+([A-Za-z0-9_]+)\s*\{([^}]+)\}', content):
            name = m.group(1)
            vals = [v.strip().split('(')[0].strip() for v in m.group(2).split(',') if v.strip()]
            lines.append(f'enum {name} {{ ' + ', '.join(vals) + ' }')

        # 2. Classes
        class_matches = list(re.finditer(r'class\s+([A-Za-z0-9_]+)(?:\s+extends\s+[A-Za-z0-9_]+)?(?:\s+implements\s+[A-Za-z0-9_,\s]+)?(?:\s+with\s+[A-Za-z0-9_,\s]+)?\s*\{', content))
        for i, cm in enumerate(class_matches):
            cname = cm.group(1)
            lines.append(f'class {cname}:')
            start = cm.end()
            end = class_matches[i+1].start() if i+1 < len(class_matches) else len(content)
            body = content[start:end]

            # Constructors
            for ctor_m in re.finditer(r'(?:const\s+)?(?:factory\s+)?\b' + cname + r'(?:\.[A-Za-z0-9_]+)?\s*\(([^)]*)\)', body):
                params = ctor_m.group(1).strip()
                lines.append(f'  Constructor: {cname}({params})')

            # Public methods
            for meth_m in re.finditer(r'^\s*([A-Za-z0-9_<>?,\s]+)\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)\s*(?:async\s*)?(?:\{|=>)', body, re.MULTILINE):
                ret_type, mname, params = meth_m.group(1).strip(), meth_m.group(2).strip(), meth_m.group(3).strip()
                if mname != cname and not mname.startswith('_'):
                    lines.append(f'  Method: {ret_type} {mname}({params})')

            # Public getters
            for get_m in re.finditer(r'^\s*([A-Za-z0-9_<>?,\s]+)\s+get\s+([a-zA-Z0-9_]+)', body, re.MULTILINE):
                lines.append(f'  Getter: {get_m.group(1).strip()} get {get_m.group(2).strip()}')

        return lines

    @classmethod
    def _extract_python_signatures(cls, content: str) -> list:
        lines = []
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    bases = [b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else '') for b in node.bases]
                    base_str = f"({', '.join(b for b in bases if b)})" if any(bases) else ""
                    lines.append(f"class {node.name}{base_str}:")
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            args = [a.arg for a in sub.args.args if a.arg != 'self']
                            lines.append(f"  def {sub.name}({', '.join(args)}):")
                        elif isinstance(sub, ast.Assign):
                            for target in sub.targets:
                                if isinstance(target, ast.Name):
                                    val_str = ""
                                    if isinstance(sub.value, ast.Call):
                                        func_name = sub.value.func.attr if isinstance(sub.value.func, ast.Attribute) else ''
                                        val_str = f" = models.{func_name}(...)" if func_name else ""
                                    lines.append(f"  {target.id}{val_str}")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in node.args.args]
                    lines.append(f"def {node.name}({', '.join(args)}):")
        except Exception:
            pass
        return lines

    @classmethod
    def extract_signatures(cls, files_dict: dict) -> dict:
        """Extracts top signatures (classes, defs, exports, enums, constructors) from generated files for cross-file alignment."""
        sigs = {}
        for path, content in (files_dict or {}).items():
            if not content:
                continue

            if path.endswith('.dart'):
                sig_lines = cls._extract_dart_signatures(content)
                sigs[path] = "\n".join(sig_lines[:30]) if sig_lines else content[:400]
            elif path.endswith('.py'):
                sig_lines = cls._extract_python_signatures(content)
                sigs[path] = "\n".join(sig_lines[:30]) if sig_lines else content[:400]
            else:
                sig_lines = []
                for line in content.splitlines():
                    stripped = line.strip()
                    if (stripped.startswith(('class ', 'def ', 'function ', 'export ', 'void ', 'Future<', 'Widget ', 'enum ', 'type ', 'interface '))
                        or 'models.Model' in stripped or 'router.' in stripped or 'app.' in stripped):
                        sig_lines.append(stripped)
                sigs[path] = "\n".join(sig_lines[:25]) if sig_lines else content[:400]
        return sigs

    @classmethod
    def generate_code_for_module(
        cls, 
        module_name: str, 
        requirements_summary: str, 
        modifications: str = "", 
        tech_stack: str = None,
        all_files: list = None,
        existing_files: dict = None,
        provider_name: str = None,
        session = None,
        user = None
    ) -> str:
        signatures = cls.extract_signatures(existing_files) if existing_files else None
        prompt = PromptTemplates.get_code_generation_prompt(
            requirements_summary=requirements_summary,
            module_name=module_name,
            tech_stack=tech_stack,
            all_files=all_files,
            existing_signatures=signatures
        )
        if module_name.endswith('.html'):
            prompt += (
                "\n\nCRITICAL REQUIREMENT FOR HTML:\n"
                "Return ONLY executable, clean HTML markup (starting with <!DOCTYPE html> or <html>). "
                "Do NOT return markdown tutorials, how-to-run instructions, or explanation steps."
            )
        if modifications:
            prompt += f"\n\nModifications requested by user: {modifications}"
            
        code = LLMRouter.generate(prompt=prompt, provider_name=provider_name, purpose='codegen', session=session, user=user)
        
        # Clean up code blocks if LLM returned markdown triple backticks
        if "```" in code:
            lines = code.splitlines()
            code_lines = []
            in_code = False
            for line in lines:
                if line.strip().startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    code_lines.append(line)
            if code_lines:
                code = "\n".join(code_lines).strip()
            else:
                # Fences might have been just prefix/suffix
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                code = "\n".join(lines).strip()
            
        return code
