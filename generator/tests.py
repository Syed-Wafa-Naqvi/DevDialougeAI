from django.test import TestCase
from generator.syntax_validator import SyntaxValidator
from generator.code_builder import CodeBuilder

class GeneratorTestCase(TestCase):
    def test_syntax_validator_valid_python(self):
        valid, msg = SyntaxValidator.validate_code("main.py", "x = 10\nprint(x)")
        self.assertTrue(valid)

    def test_syntax_validator_invalid_python(self):
        valid, msg = SyntaxValidator.validate_code("main.py", "def foo(:")
        self.assertFalse(valid)
        self.assertIn("Syntax Error", msg)

    def test_code_builder(self):
        code = CodeBuilder.generate_code_for_module("main.py", "Build a hello world script", provider_name='free')
        self.assertIsInstance(code, str)
