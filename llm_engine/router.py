import os
import time
from django.conf import settings
from llm_engine.models import LLMCallLog
from llm_engine.providers.openai_provider import OpenAIProvider
from llm_engine.providers.claude_provider import ClaudeProvider
from llm_engine.providers.gemini_provider import GeminiProvider
from llm_engine.providers.deepseek_provider import DeepSeekProvider
from llm_engine.providers.free_provider import FreeAIProvider
from llm_engine.providers.mock_provider import MockProvider

class MockFallbackProvider(MockProvider):
    """Fallback provider extending MockProvider for backward compatibility."""
    pass

class UsageLimitExceededError(Exception):
    """Raised when user exceeds daily token usage budget or concurrency limits."""
    pass


class LLMRouter:
    @staticmethod
    def get_provider(provider_name: str = None, purpose: str = 'chat'):
        if getattr(settings, 'USE_MOCK_LLM', False):
            return MockProvider(provider_name='mock', model_name='mock-v1')

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

        # Default to Free Keyless AI Provider (LLaMA 3.3 / Qwen Coder)
        return FreeAIProvider()

    @classmethod
    def generate(cls, prompt: str, system_prompt: str = None, provider_name: str = None, purpose: str = 'chat', user = None, session = None) -> str:
        if user is None and session is not None:
            user = getattr(session, 'user', None)

        if user and getattr(user, 'is_authenticated', False):
            from django.utils import timezone
            from django.db.models import Sum
            daily_limit = getattr(settings, 'DAILY_USER_TOKEN_LIMIT', 500000)
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            logs = LLMCallLog.objects.filter(user=user, created_at__gte=today_start)
            agg = logs.aggregate(in_tot=Sum('input_tokens'), out_tot=Sum('output_tokens'))
            used_tokens = (agg['in_tot'] or 0) + (agg['out_tot'] or 0)
            if used_tokens >= daily_limit:
                raise UsageLimitExceededError(
                    f"Daily AI token budget limit reached ({used_tokens}/{daily_limit}). "
                    "Please try again tomorrow or upgrade your plan."
                )

        start_time = time.time()
        provider = cls.get_provider(provider_name=provider_name, purpose=purpose)
        p_name = getattr(provider, 'provider_name', provider_name or 'free')
        m_name = getattr(provider, 'model_name', 'default')

        in_tokens = len(prompt) // 4
        fallback_used = False
        success = True
        err_msg = ""
        result = ""

        try:
            result = provider.generate_completion(prompt=prompt, system_prompt=system_prompt)
        except Exception as e:
            err_msg = str(e)[:500]
            fallback_used = True
            if p_name != 'free':
                try:
                    free_fallback = FreeAIProvider()
                    result = free_fallback.generate_completion(prompt=prompt, system_prompt=system_prompt)
                    if result:
                        p_name = "free_fallback"
                except Exception:
                    pass
            if not result:
                fallback = MockProvider()
                p_name = "mock_fallback"
                result = fallback.generate_completion(prompt=prompt, system_prompt=system_prompt)

        latency_ms = int((time.time() - start_time) * 1000)
        out_tokens = len(result) // 4

        # Log LLM Call
        try:
            log_bodies = getattr(settings, 'LLM_LOG_BODIES', False)
            LLMCallLog.objects.create(
                user=user,
                session=session,
                purpose=purpose,
                provider=p_name,
                model_id=m_name,
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                is_token_estimated=True,
                latency_ms=latency_ms,
                estimated_cost=0.0,
                success=success,
                error_message=err_msg,
                fallback_used=fallback_used,
                prompt_body=prompt[:2000] if log_bodies else None,
                response_body=result[:2000] if log_bodies else None
            )
        except Exception:
            pass

        return result


