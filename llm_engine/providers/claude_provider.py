import json
import urllib.request
import urllib.error
from llm_engine.providers.base import BaseLLMProvider

class ClaudeProvider(BaseLLMProvider):
    def __init__(self, api_key: str = None, model: str = "claude-3-5-sonnet-20241022"):
        super().__init__(api_key=api_key, model=model)

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        if not self.is_available():
            raise ValueError("Anthropic Claude API key is missing.")

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system_prompt:
            payload["system"] = system_prompt

        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data['content'][0]['text'].strip()
        except Exception as e:
            raise RuntimeError(f"Claude API Error: {str(e)}")
