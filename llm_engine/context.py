from django.conf import settings
from llm_engine.prompt_templates import PromptTemplates

class ContextBuilder:
    MODEL_CONTEXT_BUDGETS = {
        'default': 8000,
        'gemini-2.5-flash-lite': 32000,
        'gemini-3-flash-preview': 32000,
        'gemini-3.8-flash': 32000,
        'gemini-2.0-flash': 16000,
        'gemini-1.5-pro': 32000,
        'gpt-4o': 16000,
        'gpt-4o-mini': 8000,
        'claude-3-5-sonnet-latest': 16000,
        'qwen-2.5-coder': 8000,
        'llama-3.3-70b': 8000,
    }

    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return len(text) // 4

    @classmethod
    def refresh_conversation_summary(cls, session, provider_name: str = None) -> str:
        """
        Refreshes the rolling conversation summary for long sessions (>= 10 messages).
        """
        from llm_engine.router import LLMRouter

        msg_count = session.messages.count()
        if msg_count < 10:
            return session.summary_text

        # Summarize all but the last 4 recent messages
        older_msgs = session.messages.all()[:msg_count - 4]
        transcript = "\n".join([f"{m.role.capitalize()}: {m.content}" for m in older_msgs])

        prompt = (
            f"Summarize this software design conversation transcript into a concise technical background statement:\n\n"
            f"{transcript}\n\n"
            "Include key decisions, tech stack choices, and user preferences."
        )

        try:
            summary = LLMRouter.generate(
                prompt=prompt,
                system_prompt="You are an expert technical documentation summarizer.",
                provider_name=provider_name,
                purpose='summary',
                session=session
            )
            session.summary_text = summary
            session.save(update_fields=['summary_text'])
            return summary
        except Exception:
            return session.summary_text

    @classmethod
    def build_context(cls, session, purpose: str = 'chat', task_prompt: str = '', model_id: str = 'default', provider_name: str = None) -> dict:
        """
        Assembles prompt context in strict priority order while enforcing token budgets.
        Priority: System Prompt -> SRS/Summary -> Plan Contract -> Task Prompt -> Recent Messages.
        """
        budget = cls.MODEL_CONTEXT_BUDGETS.get(model_id, cls.MODEL_CONTEXT_BUDGETS['default'])

        # 1. System Prompt
        if purpose == 'chat':
            system_prompt = PromptTemplates.get_interview_system_prompt()
        elif purpose == 'completeness':
            system_prompt = PromptTemplates.get_completeness_system_prompt()
        elif purpose == 'ambiguity':
            system_prompt = PromptTemplates.get_ambiguity_system_prompt()
        else:
            system_prompt = "You are DevDialogue AI, an expert software architect."

        sys_tokens = cls.estimate_tokens(system_prompt)
        remaining_budget = max(500, budget - sys_tokens)

        context_parts = []

        # 2. SRS Summary or Rolling Conversation Summary
        srs_msgs = session.messages.filter(role='assistant', content__contains="Project Requirements Summary")
        if srs_msgs.exists():
            srs_text = f"ACTIVE SRS SPECIFICATION:\n{srs_msgs.last().content}"
            context_parts.append(srs_text)
        elif session.summary_text:
            context_parts.append(f"CONVERSATION BACKGROUND:\n{session.summary_text}")

        # 3. Plan Contract
        plan_obj = session.plans.filter(status__in=['approved', 'draft']).first()
        if plan_obj:
            plan_str = f"APPROVED PLAN CONTRACT (v{plan_obj.version}):\nFiles: {plan_obj.generation_order}"
            context_parts.append(plan_str)

        # 4. Current Task Prompt
        if task_prompt:
            context_parts.append(f"CURRENT TASK:\n{task_prompt}")

        # Calculate tokens used so far by high-priority blocks
        priority_text = "\n\n".join(context_parts)
        priority_tokens = cls.estimate_tokens(priority_text)
        avail_for_history = max(200, remaining_budget - priority_tokens)

        # 5. Recent Messages (fitting within remaining token budget)
        recent_msgs = list(session.messages.all().order_by('-timestamp')[:10])
        recent_msgs.reverse()

        history_parts = []
        hist_tokens = 0

        for msg in reversed(recent_msgs):
            line = f"{msg.role.capitalize()}: {msg.content}"
            t_count = cls.estimate_tokens(line)
            if hist_tokens + t_count > avail_for_history:
                break
            history_parts.insert(0, line)
            hist_tokens += t_count

        if history_parts:
            context_parts.append("RECENT MESSAGES:\n" + "\n".join(history_parts))

        assembled_prompt = "\n\n".join(context_parts)
        total_tokens = cls.estimate_tokens(system_prompt + assembled_prompt)

        return {
            'assembled_prompt': assembled_prompt,
            'system_prompt': system_prompt,
            'token_count': total_tokens
        }
