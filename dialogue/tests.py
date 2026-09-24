from django.test import TestCase
from dialogue.completeness import CompletenessEngine
from dialogue.interviewer import InterviewerService
from dialogue.synthesizer import SRSSynthesizer
from dialogue.ambiguity import AmbiguityChecker

class DialogueEngineTestCase(TestCase):
    def test_completeness_triggers(self):
        history = [{'role': 'user', 'content': 'I want a Python API'}]
        self.assertTrue(CompletenessEngine.should_synthesize_summary(history, 'summary'))
        self.assertFalse(CompletenessEngine.should_synthesize_summary(history, 'hello'))

    def test_calculate_score(self):
        history = [{'role': 'user', 'content': 'Python backend'}]
        score = CompletenessEngine.calculate_score(history, provider_name='free')
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_interviewer_service(self):
        history = [{'role': 'user', 'content': 'Build a Django task app'}]
        q = InterviewerService.generate_next_question(history, provider_name='free')
        self.assertIsInstance(q, str)

    def test_synthesizer(self):
        history = [{'role': 'user', 'content': 'Build a Django task app'}]
        summary = SRSSynthesizer.synthesize_summary(history, provider_name='free')
        self.assertIn("Requirements", summary)
