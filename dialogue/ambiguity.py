from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class AmbiguityChecker:
    @classmethod
    def check_ambiguity(cls, conversation_history: list, provider_name: str = None) -> str:
        messages_text = "\n".join([f"{m.get('role')}: {m.get('content')}" for m in conversation_history])
        prompt = f"Analyze this conversation for conflicting requirements:\n\n{messages_text}"
        system_prompt = PromptTemplates.get_ambiguity_system_prompt()
        return LLMRouter.generate(prompt=prompt, system_prompt=system_prompt, provider_name=provider_name)
