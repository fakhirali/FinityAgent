import re
import shlex

# Patterns checked against the whole command string (span-aware, e.g.
# pipe-into-shell and fork bombs contain | ; && which would be split apart).
WHOLE_COMMAND_DENY_PATTERNS = [
    r"\b(?:curl|wget)\b[^|]*\|\s*(?:ba|z)?sh\b",
    r":\(\)\s*\{.*\};\s*:",            # fork bomb
]

# Patterns checked against each command segment (split on ; && || |).
SEGMENT_DENY_PATTERNS = [
    r"^\s*(sudo|su|doas|pkexec|runuser)\b",
    r"^\s*:()\s*\{.*\};\s*:",          # fork bomb
    r"\bmkfs\b",
    r"\bdd\s+if=.*\bof=/dev/[sh]d[a-z]\b",
]

# rm -rf on filesystem roots (allows /tmp, /var/folders, relative paths)
ROOT_DELETE_PATTERN = re.compile(
    r"\brm\s+(?:-\w+\s+)*-[a-zA-Z]*rf?[a-zA-Z]*\s+(\"[^\"]*\"|\S+)")

SAFE_ROOTS = ("/tmp", "/var/folders", "./", "../")


def _split_segments(command: str) -> list[str]:
    parts = re.split(r";|&&|\|\||\|", command)
    return [p for p in parts if p.strip()]


def is_denied(command: str) -> bool:
    for pattern in WHOLE_COMMAND_DENY_PATTERNS:
        if re.search(pattern, command):
            return True
    for segment in _split_segments(command):
        for pattern in SEGMENT_DENY_PATTERNS:
            if re.search(pattern, segment):
                return True
        if _is_root_delete(segment):
            return True
    return False


def _is_root_delete(segment: str) -> bool:
    m = ROOT_DELETE_PATTERN.search(segment)
    if not m:
        return False
    target = m.group(1).strip("'\"")
    if target in ("/", "/.", "/*"):
        return True
    if target.startswith("/") and not target.startswith(SAFE_ROOTS):
        return True
    if target in ("~", "$HOME", "~/", "$HOME/"):
        return True
    return False


def command_prefix(command: str) -> str:
    """Human-meaningful prefix for approval cards, e.g. 'git status'."""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if not parts:
        return command
    head = parts[0]
    if len(parts) > 1:
        head += " " + parts[1]
    return head
