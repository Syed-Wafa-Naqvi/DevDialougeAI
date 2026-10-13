from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class InterviewerService:
    @classmethod
    def generate_next_question(cls, conversation_history: list, provider_name: str = None) -> str:
        messages_text = "\n".join([f"{m.get('role').capitalize()}: {m.get('content')}" for m in conversation_history])
        
        user_msgs = [m.get('content', '') for m in conversation_history if m.get('role') == 'user']
        latest_msg = user_msgs[-1] if user_msgs else ""
        
        prompt = (
            f"Full Conversation Transcript:\n{messages_text}\n\n"
            f"LATEST USER INPUT: \"{latest_msg}\"\n\n"
            "INSTRUCTIONS:\n"
            "1. DIRECT RESPONSE: If the latest user input contains a question, query, greeting, or off-topic prompt, answer it directly, factually, and accurately in 1-2 sentences FIRST. Do not ignore their question.\n"
            "2. PIVOT TO ARCHITECTURE: After providing the direct response, transition smoothly to discussing their software project, asking the next relevant question about their architecture, stack, database, or features."
        )
        
        system_prompt = PromptTemplates.get_interview_system_prompt()
        return LLMRouter.generate(prompt=prompt, system_prompt=system_prompt, provider_name=provider_name)
