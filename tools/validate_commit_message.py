"""Validate repository commit messages.

HomeworkHelperServer commit messages are intentionally Korean-first and
hierarchical.  This script is used by `.githooks/commit-msg` and by tests so the
policy stays executable instead of living only in prose.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


HANGUL_RE = re.compile(r"[가-힣]")
CONVENTIONAL_PREFIX_RE = re.compile(
    r"^(?:build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(?:\([^)]+\))?!?:",
    re.IGNORECASE,
)
BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S")
TOP_LEVEL_BULLET_RE = re.compile(r"^(?:[-*]|\d+[.)])\s+\S")
NESTED_BULLET_RE = re.compile(r"^\s{2,}(?:[-*]|\d+[.)])\s+\S")
PLACEHOLDER_RE = re.compile(r"(?:TODO|TBD|\.{3}|미정|추후 작성)", re.IGNORECASE)


def _strip_comment_lines(message: str) -> list[str]:
    return [line.rstrip() for line in message.splitlines() if not line.lstrip().startswith("#")]


def _non_empty_indexes(lines: list[str]) -> list[int]:
    return [index for index, line in enumerate(lines) if line.strip()]


def _top_level_content(line: str) -> str:
    return re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line).strip()


def _has_required_section(lines: list[str], *names: str) -> bool:
    for line in lines:
        content = _top_level_content(line)
        normalized = content.rstrip(":：").strip()
        if content.endswith((":","：")) and normalized in names:
            return True
    return False


def validate_message(message: str) -> list[str]:
    """Return validation errors for a commit message."""

    lines = _strip_comment_lines(message)
    non_empty = _non_empty_indexes(lines)
    if not non_empty:
        return ["커밋 메시지가 비어 있습니다."]

    subject_index = non_empty[0]
    subject = lines[subject_index].strip()
    errors: list[str] = []

    if not HANGUL_RE.search(subject):
        errors.append("제목에는 한국어 요약이 포함되어야 합니다.")
    if CONVENTIONAL_PREFIX_RE.search(subject):
        errors.append("영문 Conventional Commit 접두사는 사용하지 않습니다.")
    if len(subject) > 80:
        errors.append("제목은 80자 이내로 간결하게 작성합니다.")

    if len(lines) <= subject_index + 1 or lines[subject_index + 1].strip():
        errors.append("제목과 본문 사이에는 빈 줄을 둡니다.")

    body_lines = lines[subject_index + 1 :]
    body_non_empty = [line for line in body_lines if line.strip()]
    if not body_non_empty:
        errors.append("본문에는 계층 목록을 작성해야 합니다.")
        return errors

    bullet_lines = [line for line in body_non_empty if BULLET_RE.match(line)]
    top_level_bullets = [line for line in body_non_empty if TOP_LEVEL_BULLET_RE.match(line)]
    nested_bullets = [line for line in body_non_empty if NESTED_BULLET_RE.match(line)]

    if len(top_level_bullets) < 2:
        errors.append("본문에는 최소 2개 이상의 최상위 목록 항목이 필요합니다.")
    if not nested_bullets:
        errors.append("본문에는 하위 목록을 포함한 계층 구조가 필요합니다.")

    if not _has_required_section(top_level_bullets, "변경 사항", "주요 변경", "변경"):
        errors.append("최상위 목록에 '변경 사항' 항목을 포함해야 합니다.")
    if not _has_required_section(top_level_bullets, "검증", "검증 결과"):
        errors.append("최상위 목록에 '검증' 항목을 포함해야 합니다.")

    for line in top_level_bullets:
        if not HANGUL_RE.search(line):
            errors.append("최상위 목록 항목은 한국어로 작성해야 합니다.")
            break

    for line in bullet_lines:
        if PLACEHOLDER_RE.search(line):
            errors.append("목록에는 TODO/TBD/미정 같은 placeholder를 남기지 않습니다.")
            break

    return errors


def validate_file(path: Path) -> list[str]:
    return validate_message(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate HomeworkHelperServer commit messages.")
    parser.add_argument("message_file", type=Path)
    args = parser.parse_args(argv)

    errors = validate_file(args.message_file)
    if not errors:
        return 0

    print("커밋 메시지 정책 위반:", file=sys.stderr)
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    print("", file=sys.stderr)
    print("필수 형식:", file=sys.stderr)
    print("한국어 제목", file=sys.stderr)
    print("", file=sys.stderr)
    print("- 변경 사항:", file=sys.stderr)
    print("  - 실제 변경 내용을 작성합니다.", file=sys.stderr)
    print("- 검증:", file=sys.stderr)
    print("  - 실행한 검증 명령과 결과를 작성합니다.", file=sys.stderr)
    print("", file=sys.stderr)
    print("자세한 정책: docs/development/commit-message-policy.md", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
