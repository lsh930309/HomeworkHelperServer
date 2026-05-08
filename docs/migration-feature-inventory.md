# 신/구 GUI 마이그레이션 기능 인벤토리

이 문서는 PyQt 기본 GUI에서 새 Tauri/React GUI로 전환할 때 기능 및 데이터 유실을 막기 위한 기능 인벤토리다. 기계 검증용 원본은 `tests/migration/feature_matrix.json`이며, 이 문서의 Feature ID는 해당 JSON과 동일해야 한다.

## 전환 판정 규칙

- `data_risk=high` 기능은 자동 보존 테스트 또는 Windows 수동 smoke 항목이 반드시 있어야 한다.
- `new_gui_status=missing` 기능은 새 GUI 기본 전환 전 구현 또는 명시적 PyQt fallback 유지가 필요하다.
- 모든 DB write는 API/CRUD/Beholder 경계를 지나야 하며, UI/router 직접 commit은 금지한다.
- 기본 실행 파일은 아직 `homework_helper.exe`/PyQt이며, 새 GUI는 `homework_helper_gui.exe` 미리보기 shell이다.

## 기능 목록 요약

| ID | 기능군 | 현재 PyQt | 새 GUI | 데이터 위험 | 전환 판단 |
| --- | --- | --- | --- | --- | --- |
| APP-001 | 기본 앱 shell + 새 GUI 패키징 | complete | partial | low | 새 GUI는 미리보기 shell 유지 |
| APP-002 | 단일 인스턴스/트레이 | complete | missing | medium | PyQt fallback 필요 |
| GAME-001 | 게임 CRUD/실행 방식 | complete | partial | high | CRUD/API/Beholder 테스트 필수 |
| GAME-002 | 게임 실행 | complete | partial | medium | Windows smoke 필요 |
| WEB-001 | 웹 바로가기 | complete | complete | high | 자동 테스트 유지 |
| SETTINGS-001 | 전역 설정 | complete | partial | high | 저장 보존 테스트 필수 |
| SETTINGS-002 | 설정 계약 동기화 | complete | partial | high | model/schema/runtime/migration 동기화 필수 |
| SIDEBAR-001 | 사이드바/볼륨/오버레이 | complete | missing | high | 새 GUI 기본 전환 전 구현 필요 |
| SESSION-001 | 세션 기록/충돌 복구 | complete | partial | high | Beholder 테스트 필수 |
| SCHEDULER-001 | 스케줄러/알림 | complete | missing | medium | Windows smoke 필요 |
| DASHBOARD-001 | 대시보드 analytics | complete | complete | medium | API 테스트 유지 |
| HOYOLAB-001 | HoYoLab 스태미나 | complete | missing | high | PyQt fallback + smoke 필요 |
| SCREENSHOT-001 | 스크린샷 | complete | missing | high | Windows smoke 필요 |
| RECORDING-001 | OBS 녹화 | complete | missing | high | Windows smoke 필요 |
| BEHOLDER-001 | 데이터 안전 감시 | complete | partial | high | 양쪽 UI incident UX 유지 |
| BACKUP-001 | DB/설정/row 백업 | complete | partial | high | 복구 smoke 필요 |
| BUILD-001 | 패키징 | complete | complete | medium | 기본 빌드에 새 GUI 포함 |
| CLIPBOARD-001 | 클립보드 payload | complete | missing | low | PyQt 기능 유지 |

## 운영 방식

- 상세 자동/수동 검증 항목은 `tests/migration/feature_matrix.json`을 수정한다.
- 기능을 추가하거나 제거하면 Feature ID를 만들고, 테스트 또는 smoke 항목을 연결한다.
- 새 GUI 기본 전환 후보가 되려면 `new_gui_status=missing`인 high-risk 기능이 없어야 한다.
