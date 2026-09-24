from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class CodeBuilder:
    @classmethod
    def generate_code_for_module(cls, module_name: str, requirements_summary: str, modifications: str = "", provider_name: str = None) -> str:
        prompt = PromptTemplates.get_code_generation_prompt(requirements_summary, module_name)
        if modifications:
            prompt += f"\n\nModifications requested by user: {modifications}"
            
        code = LLMRouter.generate(prompt=prompt, provider_name=provider_name)
        
        # Clean up code blocks if LLM returned markdown triple backticks
        if code.startswith("```"):
            lines = code.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            code = "\n".join(lines).strip()
            
        return code
