from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class CodeBuilder:
    @classmethod
    def generate_code_for_module(cls, module_name: str, requirements_summary: str, modifications: str = "", provider_name: str = None) -> str:
        prompt = PromptTemplates.get_code_generation_prompt(requirements_summary, module_name)
        if module_name.endswith('.html'):
            prompt += (
                "\n\nCRITICAL REQUIREMENT FOR HTML:\n"
                "Return ONLY executable, clean HTML markup (starting with <!DOCTYPE html> or <html>). "
                "Do NOT return markdown tutorials, how-to-run instructions, or explanation steps."
            )
        if modifications:
            prompt += f"\n\nModifications requested by user: {modifications}"
            
        code = LLMRouter.generate(prompt=prompt, provider_name=provider_name)
        
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
