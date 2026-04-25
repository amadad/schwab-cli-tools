#!/usr/bin/env python3
"""Fail when Any/broad-exception counts regress past a configured budget."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ANY_PATTERN = re.compile(r"\bAny\b")
BROAD_EXCEPT_PATTERN = re.compile(
    r"^\s*except\s+(Exception|BaseException)\b|^\s*except:\s*$", re.MULTILINE
)


def count_matches(root: Path) -> tuple[int, int]:
    any_count = 0
    broad_except_count = 0
    for path in root.rglob("*.py"):
        text = path.read_text()
        any_count += len(ANY_PATTERN.findall(text))
        broad_except_count += len(BROAD_EXCEPT_PATTERN.findall(text))
    return any_count, broad_except_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="src", help="Directory to scan")
    parser.add_argument("--max-any", type=int, required=True)
    parser.add_argument("--max-broad-catches", type=int, required=True)
    args = parser.parse_args()

    root = Path(args.root)
    any_count, broad_except_count = count_matches(root)

    print(f"quality-budget root={root} Any={any_count} broad_catches={broad_except_count}")

    failed = False
    if any_count > args.max_any:
        print(f"Any budget exceeded: {any_count} > {args.max_any}")
        failed = True
    if broad_except_count > args.max_broad_catches:
        print(
            f"Broad exception budget exceeded: {broad_except_count} > {args.max_broad_catches}"
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
