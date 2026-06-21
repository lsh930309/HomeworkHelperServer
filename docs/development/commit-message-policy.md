# 커밋 메시지 작성 정책

이 레포의 커밋 메시지는 언제 작성하더라도 **한국어, 계층 목록형, 검증 포함** 형식으로 고정한다.

## 필수 규칙

1. 제목은 한국어 요약으로 쓴다.
   - 영문 Conventional Commit 접두사(`feat:`, `fix:`, `chore:` 등)는 사용하지 않는다.
   - 파일명, 모듈명, 명령어, API명 같은 고유 식별자는 필요한 경우 원문을 유지할 수 있다.
2. 제목과 본문 사이에는 빈 줄을 둔다.
3. 본문은 계층 목록으로 작성한다.
   - 최상위 항목에는 최소한 `변경 사항`과 `검증`을 포함한다.
   - 각 최상위 항목 아래에는 실제 내용을 하위 목록으로 정리한다.
4. 검증 결과를 반드시 남긴다.
   - 테스트나 빌드를 실행했다면 명령과 결과를 적는다.
   - 실행하지 못했다면 이유와 남은 확인 방법을 적는다.
5. 병합 커밋과 되돌리기 커밋도 같은 정책을 따른다.
   - 기본 Git 메시지인 `Merge ...`, `Revert ...`를 그대로 커밋하지 않는다.

## 권장 템플릿

```text
정책: 커밋 메시지 작성 규칙을 고정한다

- 변경 사항:
  - repo-local AGENTS.md에 커밋 메시지 작성 계약을 추가한다.
  - Git hook과 검증 스크립트로 한국어 계층 목록 형식을 확인한다.
- 검증:
  - ./.venv/bin/python -m pytest tests/test_commit_message_policy.py -q 통과.
  - tools/validate_commit_message.py로 예시 메시지 검증 통과.
```

## 로컬 고정 방법

이 브랜치에서는 다음 설정으로 추적 가능한 hook과 템플릿을 사용한다.

```bash
git config core.hooksPath .githooks
git config commit.template .gitmessage
```

설정 후 `git commit`을 실행하면 `.gitmessage`가 기본 메시지 초안으로 열리고, 저장 시 `.githooks/commit-msg`가 정책 위반을 차단한다.
