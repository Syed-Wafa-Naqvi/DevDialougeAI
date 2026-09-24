from django.test import TestCase
from llm_engine.router import LLMRouter, MockFallbackProvider

class LLMEngineTestCase(TestCase):
    def test_mock_fallback_provider(self):
        provider = MockFallbackProvider()
        self.assertTrue(provider.is_available())
        response = provider.generate_completion("interview question")
        self.assertIn("tech stack", response.lower())

    def test_router_fallback(self):
        provider = LLMRouter.get_provider("openai")
        self.assertTrue(provider.is_available())
        
        response = LLMRouter.generate("synthesize requirement summary")
        self.assertTrue("summary" in response.lower() or "requirement" in response.lower())
