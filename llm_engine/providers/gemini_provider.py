import json
import time
import urllib.request
import urllib.error
from llm_engine.providers.base import BaseLLMProvider

class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: str = None, model: str = "gemini-flash-lite-latest"):
        super().__init__(api_key=api_key, model=model)

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def _call_gemini_api(self, model: str, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            candidates = data.get('candidates', [])
            if candidates:
                parts = candidates[0].get('content', {}).get('parts', [])
                return "".join(p.get('text', '') for p in parts).strip()
            return ""

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        if not self.is_available():
            raise ValueError("Google Gemini API key is missing.")

        models_to_try = [self.model, "gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview"]
        models_to_try = list(dict.fromkeys([m for m in models_to_try if m]))


        last_error = None
        for m in models_to_try:
            for attempt in range(2):
                try:
                    res = self._call_gemini_api(m, prompt, system_prompt, temperature)
                    if res:
                        return res
                except urllib.error.HTTPError as http_err:
                    last_error = http_err
                    # Transient rate-limit (429) or service unavailable (503): backoff and retry once
                    if http_err.code in (429, 503) and attempt == 0:
                        time.sleep(2.0)
                        continue
                    break
                except Exception as e:
                    last_error = e
                    break

        raise RuntimeError(f"Gemini API Error: {str(last_error)}")
