"""Redact credential-shaped values from local operational log files."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_ROOTS = (ROOT / ".runtime", ROOT / "service" / "server" / "logs")
PATTERNS = (
    (re.compile(r"([?&]token=)(?!\[REDACTED\])[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(Authorization:\s*Bearer\s+)(?!\[REDACTED\])[^\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+(/)", re.IGNORECASE), r"\1[REDACTED]\2"),
)


def main() -> int:
    changed_files = 0
    replacements = 0
    for root in LOG_ROOTS:
        if not root.exists():
            continue
        for path in root.glob("*.log"):
            original = path.read_text(encoding="utf-8", errors="replace")
            sanitized = original
            for pattern, replacement in PATTERNS:
                sanitized, count = pattern.subn(replacement, sanitized)
                replacements += count
            if sanitized != original:
                path.write_text(sanitized, encoding="utf-8")
                changed_files += 1
    print(f"Sanitized {replacements} credential occurrence(s) in {changed_files} local log file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
