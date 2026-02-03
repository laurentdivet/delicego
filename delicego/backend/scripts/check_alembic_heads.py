"""Check Alembic heads (must be exactly 1).

Usage:
    python -m scripts.check_alembic_heads

Exit codes:
    0: OK (exactly one head)
    1: Multiple heads detected
    2: Alembic invocation error
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    try:
        out = subprocess.check_output(["alembic", "-c", "alembic.ini", "heads"], text=True).strip()
    except subprocess.CalledProcessError as e:
        print("[alembic-heads][ERROR] Failed to run alembic heads", file=sys.stderr)
        print(e.output or "", file=sys.stderr)
        return 2

    lines = [l for l in out.splitlines() if l.strip()]
    if len(lines) != 1:
        print(
            "[alembic-heads][FAIL] Multiple Alembic heads detected. "
            f"Expected 1, got {len(lines)}. Output:\n{out}",
            file=sys.stderr,
        )
        return 1

    print(f"[alembic-heads][OK] head = {lines[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
