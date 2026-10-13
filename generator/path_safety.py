import os
from pathlib import PurePosixPath

class PathSafetyError(ValueError):
    """Raised when a file path or file content violates security guardrails."""
    pass

class PathSafetyManager:
    ALLOWED_EXTENSIONS = {
        # Python
        'py', 'pyi',
        # JavaScript, TypeScript & Web
        'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs', 'html', 'htm', 'css', 'scss', 'sass', 'vue', 'svelte',
        # Mobile & Multiplatform (Flutter / Dart / Swift / Kotlin)
        'dart', 'swift', 'kt', 'kts',
        # Systems & Backend (Go, Rust, Java, C, C++, C#)
        'go', 'mod', 'sum', 'rs', 'java', 'scala', 'c', 'cpp', 'cc', 'cxx', 'h', 'hpp', 'hxx', 'cs',
        # Scripting & Web (PHP, Ruby)
        'php', 'rb',
        # Shell & Runners
        'sh', 'bash', 'zsh', 'bat', 'cmd', 'ps1',
        # Config, Manifests, Database & Docs
        'json', 'jsonc', 'md', 'txt', 'yml', 'yaml', 'toml', 'cfg', 'ini', 'sql',
        'xml', 'gradle', 'properties', 'env.example', 'gitignore', 'dockerfile', 'lock'
    }

    ALLOWED_SPECIAL_FILES = {'dockerfile', 'gitignore', 'env.example', 'makefile', 'procfile', 'gemfile', 'license', 'cname'}

    MAX_FILES_PER_PROJECT = 60
    MAX_FILE_SIZE_BYTES = 200 * 1024  # 200 KB

    @classmethod
    def validate_path(cls, path_str: str) -> str:
        """
        Validates and normalizes a file path string.
        Raises PathSafetyError if unsafe. Returns cleaned relative path string.
        """
        if not path_str or not isinstance(path_str, str):
            raise PathSafetyError("Path must be a non-empty string.")

        # Check null bytes
        if '\x00' in path_str:
            raise PathSafetyError("Null bytes are not allowed in file paths.")

        # Check absolute path or drive letter
        if os.path.isabs(path_str) or ':' in path_str:
            raise PathSafetyError(f"Absolute paths and drive letters are prohibited: '{path_str}'")

        # Normalize path
        normalized = os.path.normpath(path_str).replace('\\', '/')

        # Check path traversal
        if normalized.startswith('../') or '/../' in normalized or normalized == '..':
            raise PathSafetyError(f"Path traversal ('..') is prohibited: '{path_str}'")

        # Check hidden files / system directories
        parts = normalized.split('/')
        for part in parts:
            if part.startswith('.') and part.lower().lstrip('.') not in cls.ALLOWED_SPECIAL_FILES:
                raise PathSafetyError(f"Hidden system paths or dotfiles are prohibited: '{path_str}'")

        # Check file extension or special file
        basename = parts[-1].lower()
        if basename in cls.ALLOWED_SPECIAL_FILES or basename.lstrip('.') in cls.ALLOWED_SPECIAL_FILES:
            return normalized

        ext = basename.split('.')[-1] if '.' in basename else ''

        if ext not in cls.ALLOWED_EXTENSIONS:
            raise PathSafetyError(f"File extension '.{ext}' is not in the allowed extensions list.")

        return normalized


    @classmethod
    def validate_file_content(cls, content: str):
        """Validates file size limits."""
        if content is None:
            return
        content_bytes = content.encode('utf-8')
        if len(content_bytes) > cls.MAX_FILE_SIZE_BYTES:
            raise PathSafetyError(
                f"File content size ({len(content_bytes)} bytes) exceeds limit of {cls.MAX_FILE_SIZE_BYTES} bytes."
            )

    @classmethod
    def validate_project_file_count(cls, current_file_count: int):
        """Validates maximum file count per project."""
        if current_file_count >= cls.MAX_FILES_PER_PROJECT:
            raise PathSafetyError(
                f"Project file count limit reached ({cls.MAX_FILES_PER_PROJECT} max files allowed)."
            )
