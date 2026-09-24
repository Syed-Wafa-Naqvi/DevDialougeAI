import ast

class SyntaxValidator:
    @classmethod
    def validate_code(cls, filename: str, code_content: str) -> tuple[bool, str]:
        if filename.endswith('.py'):
            try:
                ast.parse(code_content)
                return True, "Valid Python syntax."
            except SyntaxError as e:
                return False, f"Python Syntax Error on line {e.lineno}: {e.msg}"
        return True, "No syntax validator required for this file type."
