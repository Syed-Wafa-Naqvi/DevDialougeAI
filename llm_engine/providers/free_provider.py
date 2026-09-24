import json
import urllib.request
import urllib.error
from llm_engine.providers.base import BaseLLMProvider

class FreeAIProvider(BaseLLMProvider):
    """100% Free, Keyless, Unlimited Real AI Provider (LLaMA 3.3 / Qwen Coder)."""
    def __init__(self, model: str = "openai"):
        super().__init__(api_key="FREE_KEYLESS", model=model)

    def is_available(self) -> bool:
        return True

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        url = "https://text.pollinations.ai/"
        headers = {"Content-Type": "application/json"}
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "model": self.model,
            "seed": 42
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = resp.read().decode('utf-8').strip()
                return result
        except Exception as e:
            raise RuntimeError(f"Free AI Provider Error: {str(e)}")
