import json
import re
from django.conf import settings
from llm_engine.router import LLMRouter
from llm_engine.prompt_templates import PromptTemplates

class CompletenessEngine:
    RUBRIC_WEIGHTS = {
        'core_features': 0.25,
        'data_model': 0.20,
        'auth_and_roles': 0.15,
        'tech_stack': 0.15,
        'purpose_and_users': 0.10,
        'integrations': 0.05,
        'non_functional': 0.05,
        'deployment': 0.05,
    }

    TECH_KEYWORDS = {
        "app", "application", "system", "website", "api", "database", "sql", "nosql",
        "django", "react", "vue", "angular", "python", "node", "express", "postgres",
        "postgresql", "mongodb", "auth", "authentication", "user", "service", "model",
        "schema", "frontend", "backend", "fullstack", "endpoint", "rest", "graphql",
        "microservice", "dashboard", "feature", "store", "e-commerce", "chat", "pipeline",
        "tool", "code", "architecture", "component", "jwt", "oauth"
    }

    @classmethod
    def evaluate_rubric(cls, conversation_history: list, provider_name: str = None) -> dict:
        """
        Evaluates requirements completeness against an 8-category architectural rubric.
        Returns a dict: {'score': int, 'categories': dict, 'next_questions': list, 'contradictions': list, 'is_estimated': bool}
        """
        messages_text = "\n".join([f"{m.get('role').capitalize()}: {m.get('content')}" for m in conversation_history])
        prompt = f"Analyze this software design conversation transcript:\n\n{messages_text}\n\nEvaluate requirement coverage across all 8 rubric categories."
        system_prompt = PromptTemplates.get_completeness_system_prompt()

        try:
            resp = LLMRouter.generate(prompt=prompt, system_prompt=system_prompt, provider_name=provider_name, purpose='completeness')
            from generator.protocol import EditProtocolEngine
            data = EditProtocolEngine.parse_payload(resp)

            categories = data.get('categories', {})
            score_float = 0.0
            for cat, weight in cls.RUBRIC_WEIGHTS.items():
                val_str = str(categories.get(cat, 'missing')).lower().strip()
                multiplier = 1.0 if val_str == 'covered' else (0.5 if val_str == 'partial' else 0.0)
                score_float += weight * multiplier

            score = int(round(score_float * 100))
            return {
                'score': score,
                'categories': categories,
                'next_questions': data.get('next_questions', []),
                'contradictions': data.get('contradictions', []),
                'is_estimated': False
            }
        except Exception:
            # Fallback: Keyword-based estimation
            score = cls._calculate_keyword_fallback_score(conversation_history)
            return {
                'score': score,
                'categories': {},
                'next_questions': ["What is the primary purpose and target user base of this app?"],
                'contradictions': [],
                'is_estimated': True
            }

    @classmethod
    def _calculate_keyword_fallback_score(cls, conversation_history: list) -> int:
        found_keywords = set()
        for m in conversation_history:
            if m.get('role') == 'user':
                text = m.get('content', '').lower()
                words = set(re.findall(r'\b[a-z]{3,}\b', text))
                found_keywords.update(words.intersection(cls.TECH_KEYWORDS))
        return min(len(found_keywords) * 20, 100)

    @classmethod
    def calculate_score(cls, conversation_history: list, provider_name: str = None) -> int:
        eval_res = cls.evaluate_rubric(conversation_history, provider_name=provider_name)
        return eval_res['score']

    @classmethod
    def should_synthesize_summary(cls, conversation_history: list, latest_user_msg: str, provider_name: str = None) -> bool:
        msg_lower = latest_user_msg.lower().strip()
        
        explicit_triggers = [
            "generate", "summary", "summarize", "proceed", "ready", "build code",
            "compile", "build project", "create app", "lets start", "let's start",
            "create project", "generate project", "generate now", "all files",
            "provide me all files", "provide all files", "give me all files", "give me the files",
            "don't ask more questions", "no more questions", "all files at once", "give me the code",
            "give code", "generate files", "just code", "stop asking questions"
        ]
        if any(trigger in msg_lower for trigger in explicit_triggers):
            user_msgs = [m for m in conversation_history if m.get('role') == 'user']
            if user_msgs:
                return True


        threshold = getattr(settings, 'COMPLETENESS_THRESHOLD', 70)
        score = cls.calculate_score(conversation_history, provider_name=provider_name)
        return score >= threshold

