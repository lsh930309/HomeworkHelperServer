# HomeworkHelperServer 에이전트 작업 규칙

이 파일은 이 레포에서 동작하는 Codex/OMX 에이전트와 자동화 도구가 항상 따라야 하는 repo-local 계약이다.

## 커밋 메시지 정책

- 이 레포에서 생성하는 모든 커밋 메시지는 한국어를 기본 언어로 작성한다.
  - 파일명, 명령어, API 이름, 에러 문자열 같은 고유 식별자는 필요한 경우에만 원문을 유지한다.
  - `feat:`, `fix:`, `chore:` 같은 영문 Conventional Commit 접두사는 사용하지 않는다.
- 본문은 계층 목록 구조로 작성한다.
  - 최소한 `변경 사항`과 `검증` 항목을 포함한다.
  - 각 상위 항목 아래에는 실제 내용을 하위 목록으로 빠짐없이 정리한다.
  - 검증을 실행하지 못한 경우에도 `검증` 항목에 미실행 사유와 다음 확인 방법을 명시한다.
- 병합 커밋, 되돌리기 커밋, 문서 전용 커밋도 예외 없이 같은 형식을 따른다.
  - Git의 기본 영문 merge/revert 메시지는 그대로 사용하지 않는다.
- 커밋 전에는 `.githooks/commit-msg` 또는 `tools/validate_commit_message.py` 검증을 통과해야 한다.

권장 형식은 `docs/development/commit-message-policy.md`와 `.gitmessage`를 따른다.
