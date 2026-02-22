import re

WAKE_WORD = "alice"

WAKE_REGEX = re.compile(
    rf"^\s*{WAKE_WORD}\b[\s,:-]*",
    re.IGNORECASE
)

OPEN_VERBS = (
        "open",
        "launch",
    )

FOCUS_VERBS = (
    "focus",
    "switch to",
)

CLOSE_VERBS = (
    "close",
    "exit",
)

