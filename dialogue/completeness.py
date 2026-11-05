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
    def evaluate_rubric(cls, conversation_history: list, provider_name: str = None, session=None, user=None) -> dict:
        """
        Evaluates requirements completeness against an 8-category architectural rubric.
        Returns a dict: {'score': int, 'categories': dict, 'next_questions': list, 'contradictions': list, 'is_estimated': bool}
        """
        messages_text = "\n".join([f"{m.get('role').capitalize()}: {m.get('content')}" for m in conversation_history])
        prompt = f"Analyze this software design conversation transcript:\n\n{messages_text}\n\nEvaluate requirement coverage across all 8 rubric categories."
        system_prompt = PromptTemplates.get_completeness_system_prompt()

        try:
            resp = LLMRouter.generate(prompt=prompt, system_prompt=system_prompt, provider_name=provider_name, purpose='completeness', session=session, user=user)
            clean_resp = str(resp).strip()
            
            # If the model returned an integer number directly (e.g. "100" or "85")
            num_match = re.search(r'\b([0-9]{1,3})\b', clean_resp)
            if num_match and '{' not in clean_resp:
                score = min(max(int(num_match.group(1)), 0), 100)
                return {
                    'score': score,
                    'categories': {},
                    'next_questions': [],
                    'contradictions': [],
                    'is_estimated': False
                }

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
    def calculate_score(cls, conversation_history: list, provider_name: str = None, session=None, user=None) -> int:
        eval_res = cls.evaluate_rubric(conversation_history, provider_name=provider_name, session=session, user=user)
        return eval_res['score']

    @classmethod
    def should_synthesize_summary(cls, conversation_history: list, latest_user_msg: str, provider_name: str = None, session=None, user=None) -> bool:
        msg_lower = latest_user_msg.lower().strip()
        
        explicit_patterns = [
            r'\bgenerate\b', r'\bsummary\b', r'\bsummarize\b', r'\bproceed\b', r'\bready\b',
            r'\bbuild code\b', r'\bcompile\b', r'\bbuild project\b', r'\bcreate app\b',
            r"\blet'?s start\b", r'\bcreate project\b', r'\bgenerate project\b',
            r'\bgenerate now\b', r'\ball files\b', r'\bprovide (me )?all files\b',
            r'\bgive (me )?(all )?the files\b', r"\bdon'?t ask more questions\b",
            r'\bno more questions\b', r'\ball files at once\b', r'\bgive (me )?(the )?code\b',
            r'\bgenerate files\b', r'\bjust code\b', r'\bstop asking questions\b'
        ]
        has_explicit = any(re.search(pat, msg_lower) for pat in explicit_patterns)
        has_negation = bool(re.search(r'\b(no|not|don\'?t|never|wait|stop|hold|cancel|already)\b', msg_lower))

        if has_explicit and not has_negation:
            user_msgs = [m for m in conversation_history if m.get('role') == 'user']
            if user_msgs:
                return True

        # Check if the assistant asked whether to proceed or generate files, and user responded affirmatively
        assist_msgs = [m.get('content', '').lower() for m in conversation_history if m.get('role') == 'assistant']
        if assist_msgs:
            last_assist = assist_msgs[-1]
            asked_to_proceed = any(p in last_assist for p in [
                "proceed", "generate the files", "generate the complete", "ready to proceed", 
                "generate your", "shall i generate", "should i proceed", "bring this architecture"
            ])
            user_words = set(re.findall(r'\b\w+\b', msg_lower))
            is_affirmative = any(w in user_words for w in ['sure', 'yes', 'yup', 'yeah', 'ok', 'okay', 'proceed', 'build', 'generate', 'go ahead'])
            if asked_to_proceed and is_affirmative and not has_negation:
                return True

        threshold = getattr(settings, 'COMPLETENESS_THRESHOLD', 70)
        # Fast keyword check first to avoid redundant LLM calls on early interview turns
        kw_score = cls._calculate_keyword_fallback_score(conversation_history)
        if kw_score < 50:
            return False
        score = cls.calculate_score(conversation_history, provider_name=provider_name)
        return score >= threshold


