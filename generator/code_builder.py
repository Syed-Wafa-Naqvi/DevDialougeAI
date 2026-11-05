from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class CodeBuilder:
    @classmethod
    def extract_signatures(cls, files_dict: dict) -> dict:
        """Extracts top signatures (classes, defs, exports) from generated files for cross-file alignment."""
        sigs = {}
        for path, content in (files_dict or {}).items():
            if not content:
                continue
            sig_lines = []
            for line in content.splitlines():
                stripped = line.strip()
                if (stripped.startswith(('class ', 'def ', 'function ', 'export ', 'void ', 'Future<', 'Widget '))
                    or 'models.Model' in stripped or 'router.' in stripped or 'app.' in stripped):
                    sig_lines.append(stripped)
            sigs[path] = "\n".join(sig_lines[:15]) if sig_lines else content[:300]
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
