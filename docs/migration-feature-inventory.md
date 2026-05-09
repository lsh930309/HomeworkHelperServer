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
| APP-001 | 기본 앱 shell + 새 GUI 패키징 | complete | partial | low | 새 GUI는 미리보기 shell 유지, 메인 목록 v6 상태 인디케이터 톤 유지 |
| APP-002 | 단일 인스턴스/트레이 | complete | partial | medium | 새 GUI shell hook 구현, Windows tray smoke 필요 |
| GAME-001 | 게임 CRUD/실행 방식 | complete | partial | high | CRUD/API/Beholder 테스트 필수, 새 GUI 편집은 별도 popup, 런타임 필드 편집 차단 |
| GAME-002 | 게임 실행 | complete | partial | medium | 실행 대상 계획 API/자동 테스트 유지, Windows smoke 필요 |
| WEB-001 | 웹 바로가기 | complete | complete | high | 자동 테스트 유지, 새 GUI 편집은 별도 popup, 완료 시각은 런타임만 변경 |
| SETTINGS-001 | 전역 설정 | complete | complete | high | 신규 GUI 설정 저장 parity 및 개인화 기본값/범위 오류 회귀 차단, 설정 패널은 별도 자동 크기 popup |
| SETTINGS-002 | 설정 계약 동기화 | complete | complete | high | model/schema/runtime/migration 동기화 유지 |
| SIDEBAR-001 | 사이드바/볼륨/오버레이 | complete | partial | high | 새 GUI preview 스마트 서랍/최근 스크린샷·녹화물 shell 구현, runtime API/Windows smoke 필요 |
| SESSION-001 | 세션 기록/충돌 복구 | complete | partial | high | Beholder heartbeat 기반 정전/앱재시작/legacy open 대응 |
| SCHEDULER-001 | 스케줄러/알림 | complete | partial | medium | 알림 설정 편집 및 사용자 언어 preview 가능, runtime smoke 필요 |
| DASHBOARD-001 | 대시보드 analytics | complete | complete | medium | API 테스트 및 신규 GUI v6 디자인 token 유지 |
| HOYOLAB-001 | HoYoLab 스태미나 | complete | partial | high | 새 GUI 쿠키/테스트 조회/즉시 새로고침 가능, 스태미나 범위 guard 유지, 종료 후 재동기화 runtime smoke 필요 |
| SCREENSHOT-001 | 스크린샷 | complete | partial | high | 설정 편집/키 캡처/최근 갤러리 보조 가능, capture runtime smoke 필요 |
| RECORDING-001 | OBS 녹화 | complete | partial | high | 설정 편집/OBS 설정 불러오기/최근 녹화물 보조 가능, OBS runtime 필요 |
| BEHOLDER-001 | 데이터 안전 감시 | complete | partial | high | 사용자 친화 incident UX/내부 코드명 없는 위험 라벨/DB 요약 백업 preview/스마트 세션 복구/actor별 필드·값 범위 guard 유지, Windows 복구 smoke 필요 |
| BACKUP-001 | DB/설정/row 백업 | complete | partial | high | 새 GUI 복구 preview에 DB 요약/영향 안내 제공, 실제 복구 smoke 필요 |
| BUILD-001 | 패키징 | complete | complete | medium | 기본 빌드에 새 GUI 포함 |
| CLIPBOARD-001 | 클립보드 payload | complete | partial | low | 새 GUI API payload 및 사이드바 갤러리 복사 경계 제공, gallery runtime smoke 필요 |

## 실사용 데이터 복제 검증

- 로컬에 `HomeworkHelper.zip`이 있으면 `tools/verify_project.py`는 ZIP에서 새 임시 AppData 복제본을 만들어 real-data fixture 검증을 함께 실행한다.
- 원본 ZIP과 추출물은 Git 추적 대상이 아니며, 테스트는 복제 DB/리소스만 읽거나 수정한다.
- `python tools/verify_project.py --require-real-data`는 ZIP 부재를 실패로 처리해 마이그레이션 작업자가 실사용 데이터 검증을 의무화할 때 사용한다.

## 운영 방식

- 상세 자동/수동 검증 항목은 `tests/migration/feature_matrix.json`을 수정한다.
- 기능을 추가하거나 제거하면 Feature ID를 만들고, 테스트 또는 smoke 항목을 연결한다.
- 새 GUI 기본 전환 후보가 되려면 `new_gui_status=missing`인 high-risk 기능이 없어야 하며, `partial` runtime 항목의 Windows smoke가 완료되어야 한다.
