# 2026-06-10 기준, 현재 추가를 고려하고 있는 기능 정리

## rough idea
- 각 항목당 각각 브랜치 하나를 할당하여 개발 후 main에 머지하는 과정을 마친 후 다음 순서의 작업을 진행할 것임.
- 현재는 간단한 아이디어만 적어둔 상태로, 현재 문서에 각각의 항목에 대한 구체적인 작업 내용을 한 번에 하나씩 정리해 나갈 예정.

---

1. [완료/v1.2.5] host: HoYoLAB/BlablaLink 자동 출석체크 기능.

   ### 요구사항 요약

   - `자동 출석체크` 기능을 기존 자원 추적과 분리된 관리 영역으로 제공한다.
   - v1 지원 대상은 provider 매핑이 확정된 `honkai_starrail`, `zenless_zone_zero`, `nikke`로 한정한다.
   - 사용자가 provider/API route를 직접 고르지 않도록 게임별 설정 row에서 내부 매핑을 사용한다.
   - 브라우저 자동화 없이 저장된 HoYoLAB/BlablaLink 쿠키를 재사용한 direct API call 방식만 사용한다.
   - 자동 실행은 host 앱 실행 중 보장하며, 앱 시작/catch-up, sleep/wake 복귀, 주기 평가에서 reset window별 1회 실행을 관리한다.
   - 성공/이미 완료는 조용히 로그에 남기고, 인증 만료·보안 인증·게임 로그인·route 변경 등 사용자 조치가 필요한 실패만 알림 대상으로 삼는다.

   ### 구현 결과

   - HoYoLAB provider는 `honkai_starrail`과 `zenless_zone_zero` 출석 상태 확인/출석 실행을 지원하고, 저장된 `HoYoLabConfig` 쿠키를 재사용한다.
   - BlablaLink/NIKKE provider는 task status probe와 `DailyCheckIn` 실행을 지원하며, 세션 쿠키 갱신을 감지해 기존 `NikkeConfig` 저장소에 반영한다.
   - 결과 상태는 `success`, `already_done`, `auth_required`, `challenge_required`, `game_login_required`, `route_error`, `network_error`, `unavailable` 등으로 정규화했다.
   - `자원/출석 관리` UI를 `계정/토큰`, `자동 출석`, `최근 로그` 탭으로 분리하고, 게임별 opt-in checkbox, 상태 확인, 즉시 출첵, 로그/오류 복사 UX를 제공한다.
   - `daily_checkin_settings`, `daily_checkin_logs`, `provider_credential_health` 저장 구조를 추가해 설정, 실행 로그, provider 인증 상태를 자원 추적과 분리했다.
   - 스케줄러는 앱 시작, sleep/wake 복귀, 5분 주기 평가, provider reset time(HoYoLAB KST 01:00 / BlablaLink KST 09:00), reset window 중복 실행 방지, 일시 오류 30분 재시도, 사용자 조치 필요 실패의 중복 자동 재시도 방지를 처리한다.
   - opt-in 직후에는 POST 없이 read-only 상태 확인을 먼저 수행하며, 수동 쿠키 유효성 검사와 자동 기능 감지 결과를 provider health에 반영한다.

   ### 완료 상태

   - Windows host의 실제 저장 세션으로 HoYoLAB/BlablaLink direct API 출석을 검증했고, 세 지원 게임의 모바일 앱/웹 출석 반영을 확인했다.
   - 약 1주 이상 실제 자동 출석체크 운용에서 문제 없이 동작해 v1 구현 성공 기준을 충족한 것으로 정리한다.
   - 해당 구현은 `main`에 병합되었으며 현재 릴리스 기준은 `v1.2.5` 태그로 관리한다.

2. host: 개별 게임별로 [프로세스 실행] 방식으로 실행 시, 함께 인자를 전달할 수 있는 opt-in 기능을 추가한다. (예: 젠레스존제로를 실행 시, 인자로서 --launcher-mode를 전달하도록 지원)


3. host & client: openSSH 의존성을 덜기 위해, host에 sleep/shutdown/restart 제어 기능을 만들고, client가 http 요청을 통해 이것을 제어하도록 구성하여 원격 전원 관리 기능에서 openSSH 의존성을 제거.


4. (experimental)host: 아직도 원인을 알 수 없는 gui 버벅임 현상이나, OBS binding이 꼬이는 문제(OBS에서 기인한 문제일 가능성도 있음) 등을 자체적으로 진단/자동으로 프로세스를 재시작하는 등의 원활한 동작 상태를 유지하기 위한 셀프 안정화 기능 구현, 또는 명확한 원인 진단.


5. host: sidebar 개선 및 기능 개발(호출/숨김 동작 개선 및 편의성 제고, main gui의 기능 일부 이식 등 고려 중).
