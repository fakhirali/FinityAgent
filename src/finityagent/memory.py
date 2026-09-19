"""Long-term agent memory: one fixed-size text file (Hermes-style but 1 file)."""
from pathlib import Path

from .config import FINITY_DIR

MEMORY_PATH = FINITY_DIR / "MEMORY.md"
MAX_CHARS = 4000


def read_memory() -> str:
    return MEMORY_PATH.read_text() if MEMORY_PATH.exists() else ""


def write_memory(text: str) -> bool:
    """Append/overwrite memory. Returns False if over the size cap."""
    if len(text) > MAX_CHARS:
        return False
    FINITY_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_PATH.write_text(text)
    return True


def append_memory(text: str) -> bool:
    current = read_memory()
    if current:
        text = current.rstrip() + "\n\n" + text
    return write_memory(text)
