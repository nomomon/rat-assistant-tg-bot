"""Shared utilities."""

from pathlib import Path


def load_prompt(path: Path) -> str:
    """Read a prompt file and return its contents.

    Raises FileNotFoundError if the file is missing and ValueError if it is empty.
    """
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FileNotFoundError(f"Prompt file not found: {path}") from exc
    if not text:
        raise ValueError(f"Prompt file is empty: {path}")
    return text
