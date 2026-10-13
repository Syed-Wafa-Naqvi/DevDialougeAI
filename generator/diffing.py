import difflib

class DiffEngine:
    @staticmethod
    def generate_unified_diff(old_content: str, new_content: str, from_label: str = "v1", to_label: str = "v2") -> str:
        """
        Generates a unified diff string between old_content and new_content.
        """
        old_lines = (old_content or "").splitlines(keepends=True)
        new_lines = (new_content or "").splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=from_label,
            tofile=to_label,
            lineterm=""
        )
        return "".join(diff)
