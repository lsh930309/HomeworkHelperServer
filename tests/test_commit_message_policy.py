from tools.validate_commit_message import validate_message


def test_accepts_korean_hierarchical_commit_message():
    message = """정책: 커밋 메시지 작성 규칙을 고정한다

- 변경 사항:
  - repo-local AGENTS.md에 커밋 메시지 작성 계약을 추가한다.
  - Git hook과 검증 스크립트로 정책 위반을 차단한다.
- 검증:
  - ./.venv/bin/python -m pytest tests/test_commit_message_policy.py -q 통과.
"""

    assert validate_message(message) == []


def test_rejects_english_conventional_prefix():
    message = """chore: 커밋 메시지 정책 추가

- 변경 사항:
  - 정책 문서를 추가한다.
- 검증:
  - 정적 검증을 통과한다.
"""

    assert "영문 Conventional Commit 접두사는 사용하지 않습니다." in validate_message(message)


def test_rejects_flat_message_without_required_sections():
    message = """커밋 메시지 정책 추가

- 정책 문서를 추가한다.
- 검증 스크립트를 추가한다.
"""

    errors = validate_message(message)

    assert "본문에는 하위 목록을 포함한 계층 구조가 필요합니다." in errors
    assert "최상위 목록에 '변경 사항' 항목을 포함해야 합니다." in errors
    assert "최상위 목록에 '검증' 항목을 포함해야 합니다." in errors
