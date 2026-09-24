import json
import urllib.request
import urllib.error
from llm_engine.providers.base import BaseLLMProvider

class DeepSeekProvider(BaseLLMProvider):
    def __init__(self, api_key: str = None, model: str = "deepseek-coder"):
        super().__init__(api_key=api_key, model=model)

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        if not self.is_available():
            raise ValueError("DeepSeek API key is missing.")

        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data['choices'][0]['message']['content'].strip()
        except Exception as e:
            raise RuntimeError(f"DeepSeek API Error: {str(e)}")
