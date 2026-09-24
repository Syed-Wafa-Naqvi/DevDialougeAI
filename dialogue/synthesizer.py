from llm_engine.router import LLMRouter

class SRSSynthesizer:
    @classmethod
    def synthesize_summary(cls, conversation_history: list, is_mode2: bool = False, provider_name: str = None) -> str:
        messages_text = "\n".join([f"{m.get('role').capitalize()}: {m.get('content')}" for m in conversation_history])
        
        prompt = (
            f"Analyze this software design conversation:\n\n{messages_text}\n\n"
            "Synthesize a clear, professional Project Requirements Summary in Markdown format.\n"
            "Extract:\n"
            "- **Project Concept**: (brief summary of what the software application is)\n"
            "- **Tech Stack**: (frameworks, programming languages, databases specified)\n"
            "- **Core Modules**: (main features/components)\n"
            "- **Authentication & Security**: (user auth, roles)\n"
            "- **Constraints & External APIs**: (if specified, else 'Standard REST architecture')\n\n"
            "Do NOT include off-topic chatter, greetings, or casual remarks in the summary categories.\n"
            "End with: 'I have compiled all the requirements. Should I proceed to generate the codebase?'"
        )
        if is_mode2:
            prompt += " (Mention that generation will happen incrementally, module-by-module)."
            
        system_prompt = "You are a senior software architect compiling a formal SRS requirements summary."
        return LLMRouter.generate(prompt=prompt, system_prompt=system_prompt, provider_name=provider_name)
