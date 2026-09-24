import os
from llm_engine.providers.openai_provider import OpenAIProvider
from llm_engine.providers.claude_provider import ClaudeProvider
from llm_engine.providers.gemini_provider import GeminiProvider
from llm_engine.providers.deepseek_provider import DeepSeekProvider
from llm_engine.providers.free_provider import FreeAIProvider

class MockFallbackProvider:
    """Intelligent simulation engine used when external services are unreachable."""
    def __init__(self, provider_name="fallback"):
        self.provider_name = provider_name

    def is_available(self) -> bool:
        return True

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        prompt_lower = prompt.lower()
        
        # If summarizing requirements
        if "summary" in prompt_lower or "synthesize" in prompt_lower:
            return (
                "### Project Requirements Summary\n\n"
                "- **Tech Stack**: Python (Django / FastAPI), SQLite / PostgreSQL\n"
                "- **Core Features**: User Authentication, Project & Task Management, REST APIs\n"
                "- **Authentication**: Email/Password + OTP Verification\n"
                "- **Constraints**: Secure API endpoints, responsive UI templates\n\n"
                "I have compiled all the requirements. Should I proceed to generate the codebase?"
            )

        # If asking a clarifying question in dialogue mode
        if "question" in prompt_lower or "interview" in prompt_lower or "elicit" in prompt_lower or "requirement" in prompt_lower:
            if "stack" not in prompt_lower:
                return "Great concept! What is your preferred tech stack (e.g., Python/Django, Node.js/React, FastAPI, SQLite, PostgreSQL)?"
            elif "module" not in prompt_lower and "feature" not in prompt_lower:
                return "Got it. What are the primary features or modules you want to include in this system?"
            elif "auth" not in prompt_lower:
                return "Understood. What user roles or authentication mechanisms (e.g., standard login, OTP, JWT, Admin) do you require?"
            else:
                return "Are there any specific third-party APIs, database constraints, or performance rules I should keep in mind?"
            
        # Default response
        return "I've analyzed your project specifications. Please confirm if you'd like me to proceed with code generation!"

class LLMRouter:
    @staticmethod
    def get_provider(provider_name: str = None):
        provider_name = (provider_name or os.environ.get('DEFAULT_AI_PROVIDER', 'free')).lower().strip()
        
        openai_key = os.environ.get('OPENAI_API_KEY')
        claude_key = os.environ.get('ANTHROPIC_API_KEY')
        gemini_key = os.environ.get('GEMINI_API_KEY')
        deepseek_key = os.environ.get('DEEPSEEK_API_KEY')

        if provider_name == 'openai' and openai_key:
            return OpenAIProvider(api_key=openai_key)
        elif provider_name == 'claude' and claude_key:
            return ClaudeProvider(api_key=claude_key)
        elif provider_name == 'gemini' and gemini_key:
            return GeminiProvider(api_key=gemini_key)
        elif provider_name == 'deepseek' and deepseek_key:
            return DeepSeekProvider(api_key=deepseek_key)

        # Automatic key resolution
        if gemini_key:
            return GeminiProvider(api_key=gemini_key)
        if openai_key:
            return OpenAIProvider(api_key=openai_key)
        if deepseek_key:
            return DeepSeekProvider(api_key=deepseek_key)
        if claude_key:
            return ClaudeProvider(api_key=claude_key)

        # Default to 100% Free Keyless Real AI Model (LLaMA 3.3 / Qwen Coder)
        return FreeAIProvider()

    @classmethod
    def generate(cls, prompt: str, system_prompt: str = None, provider_name: str = None) -> str:
        provider = cls.get_provider(provider_name)
        try:
            return provider.generate_completion(prompt=prompt, system_prompt=system_prompt)
        except Exception as e:
            # Fallback to mock simulation if network error occurs
            fallback = MockFallbackProvider()
            return fallback.generate_completion(prompt=prompt, system_prompt=system_prompt)
