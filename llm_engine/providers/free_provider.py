import json
import urllib.request
import urllib.parse
import urllib.error
from llm_engine.providers.base import BaseLLMProvider

class FreeAIProvider(BaseLLMProvider):
    """100% Free, Keyless, Unlimited Real AI Provider."""
    def __init__(self, model: str = "openai"):
        super().__init__(api_key="FREE_KEYLESS", model=model or "openai")

    def is_available(self) -> bool:
        return True

    def _get_headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "User-Agent": "DevDialogueAI-FreeProvider/1.0",
            "Accept": "application/json, text/plain, */*"
        }

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        headers = self._get_headers()
        
        # Safe POST to pollinations text API
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        models_to_try = [self.model if self.model in ("openai", "default") else "openai", "openai"]
        models_to_try = list(dict.fromkeys(models_to_try))

        last_error = None
        for m in models_to_try:
            payload = {
                "messages": messages,
                "model": m,
                "seed": 42
            }
            try:
                req = urllib.request.Request(
                    "https://text.pollinations.ai/",
                    data=json.dumps(payload).encode('utf-8'),
                    headers=headers,
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=25) as resp:
                    raw = resp.read().decode('utf-8').strip()
                    try:
                        data = json.loads(raw)
                        if isinstance(data, dict):
                            val = data.get('content') or data.get('text') or data.get('message')
                            if val:
                                return val.strip()
                    except Exception:
                        pass
                    if raw and not raw.startswith("<!DOCTYPE"):
                        return raw
            except Exception as e:
                last_error = e

        raise RuntimeError(f"Free AI Provider Error: {str(last_error)}")

