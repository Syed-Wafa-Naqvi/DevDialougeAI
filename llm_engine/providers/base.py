from abc import ABC, abstractmethod

class BaseLLMProvider(ABC):
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider has valid credentials / availability."""
        pass

    @abstractmethod
    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        """Generate text completion from LLM API."""
        pass
