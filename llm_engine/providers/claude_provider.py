import os
import json
import urllib.request
import urllib.error
from llm_engine.providers.base import BaseLLMProvider

class ClaudeProvider(BaseLLMProvider):
    def __init__(self, api_key: str = None, model: str = "claude-sonnet-5-5"):
        resolved_key = api_key or os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('CLAUDE_API_KEY')
        super().__init__(api_key=resolved_key, model=model)

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate_completion(self, prompt: str, system_prompt: str = None, temperature: float = 0.7) -> str:
        if not self.is_available():
            raise ValueError("Anthropic Claude API key is missing.")

        # Map display name to Anthropic API model slug if needed
        api_model = self.model
        if api_model == "claude-sonnet-5-5":
            api_model = os.environ.get('ANTHROPIC_MODEL') or os.environ.get('CLAUDE_MODEL') or "claude-3-5-sonnet-20241022"

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": api_model,
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
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode('utf-8'))
                err_msg = err_data.get('error', {}).get('message') or str(e)
            except Exception:
                err_msg = str(e)
            raise RuntimeError(f"Claude API Error: {err_msg}")
        except Exception as e:
            raise RuntimeError(f"Claude API Error: {str(e)}")
