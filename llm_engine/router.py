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
    def get_provider(provider_name: str = None, purpose: str = 'chat', user = None):
        if getattr(settings, 'USE_MOCK_LLM', False):
            return MockProvider()

        requested = (provider_name or "").lower().strip()
        
        openai_key = os.environ.get('OPENAI_API_KEY')
        claude_key = os.environ.get('ANTHROPIC_API_KEY')
        gemini_key = os.environ.get('GEMINI_API_KEY')
        deepseek_key = os.environ.get('DEEPSEEK_API_KEY')

        # Allow authenticated users to use their personal BYOK keys saved in profile
        if user and getattr(user, 'is_authenticated', False) and hasattr(user, 'profile'):
            try:
                user_openai = user.profile.get_openai_key()
                if user_openai:
                    openai_key = user_openai
            except Exception:
                pass
            try:
                user_gemini = user.profile.get_gemini_key()
                if user_gemini:
                    gemini_key = user_gemini
            except Exception:
                pass

        # 1. Explicitly requested provider
        if requested == 'free':
            return FreeAIProvider()
        elif requested == 'mock':
            return MockProvider()
        elif requested == 'gemini' and gemini_key:
            return GeminiProvider(api_key=gemini_key)
        elif requested == 'openai' and openai_key:
            return OpenAIProvider(api_key=openai_key)
        elif requested == 'claude' and claude_key:
            return ClaudeProvider(api_key=claude_key)
        elif requested == 'deepseek' and deepseek_key:
            return DeepSeekProvider(api_key=deepseek_key)

        # 2. Check Purpose Routing Table in settings if configured
        purpose_routing = getattr(settings, 'LLM_PURPOSE_ROUTING', {})
        if purpose in purpose_routing:
            for p_type, model_choice in purpose_routing[purpose]:
                p_type = p_type.lower()
                if p_type == 'gemini' and gemini_key:
                    return GeminiProvider(api_key=gemini_key, model=model_choice)
                elif p_type == 'openai' and openai_key:
                    return OpenAIProvider(api_key=openai_key, model=model_choice)
                elif p_type == 'claude' and claude_key:
                    return ClaudeProvider(api_key=claude_key, model=model_choice)
                elif p_type == 'deepseek' and deepseek_key:
                    return DeepSeekProvider(api_key=deepseek_key, model=model_choice)
                elif p_type == 'free':
                    return FreeAIProvider(model=model_choice)

        # 3. Automatic key resolution if not explicitly specified or key was missing
        if gemini_key:
            return GeminiProvider(api_key=gemini_key)
        if openai_key:
            return OpenAIProvider(api_key=openai_key)
        if deepseek_key:
            return DeepSeekProvider(api_key=deepseek_key)
        if claude_key:
            return ClaudeProvider(api_key=claude_key)

        # 4. Default to Free Keyless AI Provider (LLaMA 3.3 / Qwen Coder)
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
        provider = cls.get_provider(provider_name=provider_name, purpose=purpose, user=user)
        p_name = getattr(provider, 'provider_name', None) or (provider_name or 'free').lower()
        m_name = getattr(provider, 'model', getattr(provider, 'model_name', 'default'))

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

            # Fallback 1: Try Gemini if primary was not Gemini and Gemini key is available
            gemini_key = os.environ.get('GEMINI_API_KEY')
            if not isinstance(provider, GeminiProvider) and gemini_key:
                try:
                    gem_fallback = GeminiProvider(api_key=gemini_key)
                    result = gem_fallback.generate_completion(prompt=prompt, system_prompt=system_prompt)
                    if result:
                        p_name = "gemini_fallback"
                except Exception as e_gem:
                    err_msg += f" | Gemini fallback error: {str(e_gem)[:200]}"

            # Fallback 2: Try FreeAI if result still empty and primary was not FreeAI
            if not result and not isinstance(provider, FreeAIProvider):
                try:
                    free_fallback = FreeAIProvider()
                    result = free_fallback.generate_completion(prompt=prompt, system_prompt=system_prompt)
                    if result:
                        p_name = "free_fallback"
                except Exception as e_free:
                    err_msg += f" | FreeAI fallback error: {str(e_free)[:200]}"

            # Fallback 3: MockProvider ONLY if offline test/mock mode is explicitly enabled
            if not result:
                if getattr(settings, 'USE_MOCK_LLM', False):
                    fallback = MockProvider()
                    p_name = "mock_fallback"
                    result = fallback.generate_completion(prompt=prompt, system_prompt=system_prompt)
                else:
                    success = False
                    # Do not return fake silent canned code when all providers fail
                    err_msg = err_msg or "All AI providers failed or were unavailable."

        latency_ms = int((time.time() - start_time) * 1000)
        out_tokens = len(result) // 4 if result else 0

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
                error_message=err_msg if not success else "",
                fallback_used=fallback_used,
                prompt_body=prompt[:2000] if log_bodies else None,
                response_body=result[:2000] if log_bodies else None
            )
        except Exception:
            pass

        if not success:
            raise RuntimeError(f"AI generation failed: {err_msg}")

        return result


