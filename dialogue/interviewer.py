from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class InterviewerService:
    @classmethod
    def generate_next_question(cls, conversation_history: list, provider_name: str = None) -> str:
        messages_text = "\n".join([f"{m.get('role').capitalize()}: {m.get('content')}" for m in conversation_history])
        
        prompt = (
            f"Conversation History:\n{messages_text}\n\n"
            "Respond to the user's latest message naturally as DevDialogue AI. "
            "If they provided project details, acknowledge them and ask the next relevant technical question. "
            "If they said 'don't know' or asked a question, guide them constructively."
        )
        
        system_prompt = PromptTemplates.get_interview_system_prompt()
        return LLMRouter.generate(prompt=prompt, system_prompt=system_prompt, provider_name=provider_name)
