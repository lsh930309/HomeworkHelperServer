# Data Safety Policy

이 앱의 사용자 데이터 변경은 반드시 API/CRUD 계층을 통과해야 한다. 직접 DB 커밋, UI별 부분 객체 저장, 기본값 기반 전체 덮어쓰기는 설정 증발의 재발 원인이므로 금지한다.

## 필수 원칙

1. **저장 계약 동기화**: 다이얼로그/런타임 모델에 있는 설정은 `GlobalSettings` DB 모델, API schema, 자동 마이그레이션에 모두 존재해야 한다.
2. **부분 변경 우선**: 새 GUI처럼 일부 설정만 바꾸는 화면은 `patch_settings()`로 변경 필드만 저장한다.
3. **actor 기반 허용 범위**: 설정 저장은 `X-HH-Beholder-Actor` 또는 CRUD actor로 출처를 남기고, 해당 화면에서 수정 가능한 필드만 허용한다.
4. **커밋 전 백업**: `global_settings`, `managed_processes`, `web_shortcuts`, `process_sessions` 변경 전에는 JSON snapshot을 남긴다.
5. **비홀더 선차단**: 대량 기본값 회귀, 허용 범위 밖 컬럼 변경, 중복 open session, 열린 세션이 있는 게임 삭제, 비정상 기록값 등은 commit 전에 incident로 차단한다.
6. **사용자 결정 우선**: 비홀더는 안전한 권장안을 제시하되, 세션 병합/닫고 새로 시작/기록 닫고 삭제 같은 스마트 조치는 사용자가 선택해야 실행한다.
7. **라우터 직접 커밋 금지**: FastAPI/Tauri/PyQt 경로는 `db.commit()`을 직접 호출하지 말고 CRUD/Beholder 함수로 위임한다. Beholder 내부 incident 처리와 CRUD 내부 커밋만 예외다.

## 구현 체크리스트

- 새 설정 추가 시: DB column + schema field + runtime data model + migration + preservation test.
- 새 저장 화면 추가 시: actor 이름 + 허용 필드 집합 + 설정 보존 회귀 테스트.
- 새 DB write 추가 시: CRUD 함수에서 `BeholderOperation`을 만들고 직접 `db.commit()`을 UI/router에 두지 않는다.
- 중요 테이블 변경 시: 변경 전 snapshot을 `backups/settings` 또는 `backups/mutations/<table>`에 남긴다.
- incident UX 추가 시: `user_title`, `user_summary`, `user_impact`, `available_actions`를 함께 제공한다.
