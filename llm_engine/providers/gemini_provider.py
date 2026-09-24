import json
import urllib.request
import urllib.error
from llm_engine.providers.base import BaseLLMProvider

class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: str = None, model: str = "gemini-2.0-flash"):
        super().__init__(api_key=api_key, model=model)

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        if not self.is_available():
            raise ValueError("Google Gemini API key is missing.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System Context: {system_prompt}"}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature
            }
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                candidates = data.get('candidates', [])
                if candidates:
                    parts = candidates[0]['content']['parts']
                    return "".join(p.get('text', '') for p in parts).strip()
                return ""
        except Exception as e:
            raise RuntimeError(f"Gemini API Error: {str(e)}")
