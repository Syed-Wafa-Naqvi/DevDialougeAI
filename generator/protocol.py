import json
import re
from generator.path_safety import PathSafetyManager, PathSafetyError

class ProtocolValidationError(ValueError):
    """Raised when JSON edit payload or operations fail validation."""
    pass

class EditProtocolEngine:
    @staticmethod
    def strip_markdown_fences(raw_text: str) -> str:
        """Strips accidental ```json and ``` fences from model responses."""
        if not raw_text:
            return ""
        text = raw_text.strip()
        # Regex to strip ```json ... ``` or ``` ... ```
        pattern = r'^```(?:json)?\s*\n?(.*?)\n?```$'
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return text

    @classmethod
    def parse_payload(cls, raw_text: str) -> dict:
        """Parses raw text into JSON object after stripping fences."""
        cleaned = cls.strip_markdown_fences(raw_text)
        try:
            data = json.loads(cleaned)
            if not isinstance(data, dict):
                raise ProtocolValidationError("Model response must be a JSON object.")
            return data
        except json.JSONDecodeError as e:
            raise ProtocolValidationError(f"Invalid JSON syntax in model response: {str(e)}")

    @classmethod
    def validate_operations(cls, payload: dict, existing_files: dict) -> list:
        """
        Validates all operations in payload against existing files.
        existing_files is a dict mapping path -> file_content.
        Returns cleaned operations list if valid; raises ProtocolValidationError if any fails.
        """
        operations = payload.get('operations')
        if not isinstance(operations, list):
            raise ProtocolValidationError("Payload must contain an 'operations' array.")

        validated_ops = []
        errors = []
        simulated_files = dict(existing_files)  # Shadow dict to check exact matches and counts

        for idx, op in enumerate(operations):
            if not isinstance(op, dict):
                errors.append(f"Operation #{idx+1}: must be a JSON object.")
                continue

            op_type = op.get('op')
            path_raw = op.get('path')

            if op_type not in ('create_file', 'replace_in_file', 'delete_file'):
                errors.append(f"Operation #{idx+1}: unknown operation type '{op_type}'.")
                continue

            # Path Safety Validation
            try:
                clean_path = PathSafetyManager.validate_path(path_raw)
            except PathSafetyError as e:
                errors.append(f"Operation #{idx+1} ({path_raw}): {str(e)}")
                continue

            if op_type == 'create_file':
                content = op.get('content', '')
                try:
                    PathSafetyManager.validate_file_content(content)
                except PathSafetyError as e:
                    errors.append(f"Operation #{idx+1} ({clean_path}): {str(e)}")
                    continue

                if clean_path not in simulated_files:
                    try:
                        PathSafetyManager.validate_project_file_count(len(simulated_files))
                    except PathSafetyError as e:
                        errors.append(f"Operation #{idx+1} ({clean_path}): {str(e)}")
                        continue

                simulated_files[clean_path] = content
                validated_ops.append({
                    'op': 'create_file',
                    'path': clean_path,
                    'content': content
                })

            elif op_type == 'replace_in_file':
                old_text = op.get('old')
                new_text = op.get('new')

                if old_text is None or new_text is None:
                    errors.append(f"Operation #{idx+1} ({clean_path}): 'replace_in_file' requires 'old' and 'new' fields.")
                    continue

                if clean_path not in simulated_files:
                    errors.append(f"Operation #{idx+1} ({clean_path}): file does not exist to perform replacement.")
                    continue

                current_content = simulated_files[clean_path]
                occurrences = current_content.count(old_text)

                if occurrences == 0:
                    errors.append(
                        f"Operation #{idx+1} ({clean_path}): 'old' text content was not found in the file."
                    )
                    continue
                elif occurrences > 1:
                    errors.append(
                        f"Operation #{idx+1} ({clean_path}): 'old' text content matched multiple ({occurrences}) times. Must match exactly once."
                    )
                    continue

                updated_content = current_content.replace(old_text, new_text, 1)
                try:
                    PathSafetyManager.validate_file_content(updated_content)
                except PathSafetyError as e:
                    errors.append(f"Operation #{idx+1} ({clean_path}): {str(e)}")
                    continue

                simulated_files[clean_path] = updated_content
                validated_ops.append({
                    'op': 'replace_in_file',
                    'path': clean_path,
                    'old': old_text,
                    'new': new_text
                })

            elif op_type == 'delete_file':
                if clean_path in simulated_files:
                    del simulated_files[clean_path]

                validated_ops.append({
                    'op': 'delete_file',
                    'path': clean_path
                })

        if errors:
            raise ProtocolValidationError("Atomic validation failed:\n" + "\n".join(errors))

        return validated_ops

    @classmethod
    def apply_operations_atomically(cls, validated_ops: list, existing_files: dict) -> dict:
        """Applies pre-validated operations atomically, returning the updated files dictionary."""
        updated_files = dict(existing_files)
        for op in validated_ops:
            op_type = op['op']
            path = op['path']
            if op_type == 'create_file':
                updated_files[path] = op['content']
            elif op_type == 'replace_in_file':
                updated_files[path] = updated_files[path].replace(op['old'], op['new'], 1)
            elif op_type == 'delete_file':
                updated_files.pop(path, None)
        return updated_files
