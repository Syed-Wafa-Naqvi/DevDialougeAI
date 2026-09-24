import re
from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class CompletenessEngine:
    @classmethod
    def calculate_score(cls, conversation_history: list, provider_name: str = None) -> int:
        messages_text = "\n".join([f"{m.get('role')}: {m.get('content')}" for m in conversation_history])
        prompt = f"Calculate requirements completeness percentage (0-100) for this software design conversation:\n\n{messages_text}"
        system_prompt = PromptTemplates.get_completeness_system_prompt()
        
        try:
            resp = LLMRouter.generate(prompt=prompt, system_prompt=system_prompt, provider_name=provider_name)
            match = re.search(r'\b\d{1,3}\b', resp)
            if match:
                val = int(match.group())
                return max(0, min(val, 100))
        except Exception:
            pass
            
        user_msgs = [m for m in conversation_history if m.get('role') == 'user']
        return min(len(user_msgs) * 20, 100)

    @classmethod
    def should_synthesize_summary(cls, conversation_history: list, latest_user_msg: str) -> bool:
        msg_lower = latest_user_msg.lower().strip()
        
        # Explicit triggers
        explicit_triggers = ["generate", "summary", "proceed", "ready", "build code", "compile"]
        if any(trigger in msg_lower for trigger in explicit_triggers):
            return True
            
        # Count technical user turns (ignoring single-word off-topic messages)
        tech_turns = 0
        for m in conversation_history:
            if m.get('role') == 'user':
                content = m.get('content', '').strip().lower()
                if len(content.split()) > 2 and content not in ["i don't know", "dont know", "no idea", "hey", "hello"]:
                    tech_turns += 1
                    
        return tech_turns >= 3
