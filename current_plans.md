# 2026-06-10 기준, 현재 추가를 고려하고 있는 기능 정리

## rough idea
- 각 항목당 각각 브랜치 하나를 할당하여 개발 후 main에 머지하는 과정을 마친 후 다음 순서의 작업을 진행할 것임.
- 현재는 간단한 아이디어만 적어둔 상태로, 현재 문서에 각각의 항목에 대한 구체적인 작업 내용을 한 번에 하나씩 정리해 나갈 예정.

---

1. host: hoyolab/blablalink 자동 출석체크 기능 만들기.

   ### 현재까지 합의한 v1 방향

   - 기능 카테고리는 `자동 출석체크`로 하나로 묶되, UI에서는 게임별 row로 분리해서 보여준다.
   - 사용자가 provider/API route를 직접 고르지 않도록 한다. 등록된 게임을 기준으로 시스템 내부에서 provider와 route를 매핑한다.
     - `honkai_starrail` → HoYoLAB daily reward API
     - `zenless_zone_zero` → HoYoLAB daily reward API
     - `nikke` → BlablaLink points/task daily check-in API
   - 현재 기본 프리셋 기준 v1 UI에 노출할 대상은 위 3개 게임으로 확정한다.
     - `endfield`, `wuwa`는 현재 자동 출첵 provider 매핑이 없으므로 v1 UI에는 노출하지 않는다.
   - 기존 스태미나/리소스 추적 기능과는 분리한다.
     - 기존 HoYoLAB/BlablaLink 쿠키 저장 및 추출 기능은 재사용한다.
     - 자동 출첵 설정/상태/히스토리는 별도의 관리 다이얼로그 또는 탭에서 관리한다.
   - 자동화 엔진은 브라우저 실행 없이 direct API call 방식으로 구현한다.
     - HoYoLAB은 `genshin.py` daily reward API를 사용한다.
     - BlablaLink/NIKKE는 `NikkeConfig` 저장 쿠키와 BlablaLink task/points API를 사용한다.
     - 브라우저 자동화 계열 실행은 v1 구현 경로에서 제외한다.
   - 자동 실행은 HomeworkHelper host 앱이 실행 중일 때만 보장한다.
     - 앱 시작 시 missed/catch-up 실행을 수행한다.
     - 앱 실행 중에는 provider별 고정 reset time 이후 자동 시도한다.
     - Windows 작업 스케줄러 등 OS-level always-on job은 v1 범위에서 제외한다.
   - reset time은 사용자 설정값이 아니라 서비스 고정값으로 취급한다.
     - HoYoLAB: KST 01:00
     - BlablaLink: KST 09:00
   - 알림 정책은 `실패만 알림`을 기본으로 한다.
     - 성공/이미 완료는 조용히 기록만 남긴다.
     - 인증 만료, 보안 인증 요구, route 변경, 네트워크 실패 등 사용자 조치가 필요한 실패만 알림으로 표시한다.

   ### 2026-06-11 API 기반 출석 검증 확정

   Windows host의 실제 저장 세션으로 HoYoLAB/BlablaLink 임시 실행 버튼을 테스트했고, 이후 모바일 앱/웹에서 실제 출석 상태를 확인했다.

   - 검증 결과:
     - `honkai_starrail`: HoYoLAB 출석 체크 성공 확인
     - `zenless_zone_zero`: HoYoLAB 출석 체크 성공 확인
     - `nikke`: BlablaLink 출석 체크 성공 확인
   - 결론:
     - 세 게임 모두 브라우저 실행 없이 저장 쿠키 기반 direct API call만으로 출석 체크를 수행할 수 있음이 확인되었다.
     - v1 자동 출석체크 구현은 API-first가 아니라 API-only 기준으로 고정한다.
     - 브라우저 의존 실행 경로는 현재 계획에서 제거한다.

   ### 확정된 provider별 동작 방식

   1. HoYoLAB provider
      - 대상 게임:
        - `honkai_starrail` / 붕괴: 스타레일
        - `zenless_zone_zero` / 젠레스 존 제로
      - 인증:
        - 기존 `HoYoLabConfig`에 저장된 `ltuid_v2`, `ltoken_v2`, 선택적 `ltmid_v2` 쿠키를 재사용한다.
      - 실행:
        - `genshin.Client(cookies=...)`를 생성한다.
        - `claim_daily_reward(game=genshin.Game.STARRAIL, lang="ko-kr")`를 호출한다.
        - 이어서 `claim_daily_reward(game=genshin.Game.ZZZ, lang="ko-kr")`를 호출한다.
        - v1 자동 실행에서는 게임별 설정 row에 따라 활성화된 대상만 호출하되, 기본 순서는 스타레일 → 젠레스 존 제로로 둔다.
      - 결과 정규화:
        - 정상 보상 반환 → `success`
        - 이미 출석 완료 → `already_done`
        - 쿠키 없음/만료 → `auth_required`
        - HoYoLAB 보안 인증 요구 → `challenge_required`
        - 요청 제한/네트워크/기타 예외 → `network_error`
        - 라이브러리 사용 불가 → `unavailable`
      - 임시 버튼 관찰:
        - 현재 화면 높이에서는 HoYoLAB 결과 라벨이 일부 잘려 보일 수 있다. 실제 자동 출석 관리 UI 구현 시 게임별 row/history 형태로 표시해 이 문제를 제거한다.

   2. BlablaLink/NIKKE provider
      - 대상 게임:
        - `nikke` / 승리의 여신: 니케
      - 인증:
        - 기존 `NikkeConfig`에 저장된 BlablaLink 세션 쿠키를 재사용한다.
      - 상태 확인:
        - `GET /lip/proxy/lipass/Points/GetTaskListWithStatusV2`
        - query: `get_top=false`, `intl_game_id=nikke`
        - daily task 판별은 `task_type == 1`을 우선 사용한다.
        - 보조 판별로 `task_id == "15"` 또는 task name의 `출석`/`check` 문자열을 사용한다.
        - `reward_infos[0]`를 task top-level 값과 병합해 `is_completed`, `completed_times`, `need_completed_times`, `points`를 파싱한다.
      - 실행:
        - 상태가 `ready`일 때만 `POST /lip/proxy/lipass/Points/DailyCheckIn`을 호출한다.
        - payload: `{ "task_id": "15" }`
        - 상태 확인에서 이미 완료/인증 오류/route 오류가 확인되면 POST를 호출하지 않는다.
      - 결과 정규화:
        - status probe에서 미완료 daily task 확인 → `ready`
        - POST `code=0` → `success`
        - POST `code=1001009` 또는 완료 상태 확인 → `already_done`
        - `code=300001` 또는 `game not login` 계열 → `game_login_required`
        - 저장 쿠키 없음/만료 → `auth_required`
        - daily task를 찾지 못함/API 구조 변경 → `route_error`
        - 네트워크/JSON/HTTP 예외 → `network_error`

   ### v1 구현 단계 고정

   1. provider abstraction 추가
      - 자동 출첵 대상 descriptor 정의
      - provider별 `status/check-in` 인터페이스 분리
      - provider/API route 세부 정보는 UI에서 숨김

   2. 설정/상태 저장 추가
      - 게임별 자동 출첵 활성 여부 저장
      - 마지막 시도 시각, 마지막 결과, 오류 메시지, 다음 예정 시각 기록
      - 기존 스태미나/리소스 추적 필드와 섞지 않음

   3. 스케줄러/코디네이터 추가
      - host 앱 시작 시 catch-up
      - 앱 실행 중 provider reset time 이후 1회 실행
      - 같은 reset window 안의 중복 실행 방지 lock 적용
      - 성공/이미 완료는 히스토리에만 기록
      - 사용자 조치가 필요한 실패만 notifier로 전달

   4. 별도 관리 UI 추가
      - 등록된 게임 중 자동 출첵 매핑이 가능한 게임만 표시
      - 게임별 checkbox, 마지막 결과, 다음 예정 시각 표시
      - 수동 `상태 확인` 또는 `지금 출첵` 버튼은 게임별 row 단위로 제공
      - 임시 인증 설정 화면 버튼은 정식 관리 UI가 들어오면 제거하거나 개발자용으로 숨김

   5. 테스트 및 검증
      - provider route mapping 정적 테스트
      - HoYoLAB/BlablaLink 결과 정규화 unit test
      - scheduler catch-up/중복 방지 테스트
      - GUI layout/static test
      - 실제 외부 POST는 자동 테스트에서 mock 처리하고, 계정 상태를 바꾸는 live 실행은 수동 승인 경로에서만 수행

   ### 2026-06-11 정식 구현 반영

   - 관리 UI는 기존 `자원 추적 설정` 메뉴를 `자원/출석 관리`로 확장하고, 내부를 `계정/토큰`, `자동 출석`, `최근 로그` 탭으로 분리한다.
   - 자동 출석 opt-in은 등록된 지원 게임 row 단위로 저장하며, 기본값은 OFF로 둔다.
   - 스케줄러 동작은 다음 규칙으로 고정한다.
     - 앱 시작, sleep/wake 복귀, 앱 실행 중 5분 주기 평가에서 due 상태를 확인한다.
     - 현재 reset window에 `success` 또는 `already_done` 로그가 있으면 같은 구간에서는 다시 호출하지 않는다.
     - `network_error` 등 일시 실패는 30분 이후 재시도한다.
     - `auth_required`, `challenge_required`, `game_login_required`, `route_error` 등 사용자 조치가 필요한 실패는 해당 구간에서 중복 자동 재시도하지 않고 실패 알림만 남긴다.
   - 출석 설정/로그 저장은 신규 DB 테이블로 분리한다.
     - `daily_checkin_settings`: process별 opt-in 및 최근 결과 캐시.
     - `daily_checkin_logs`: 모든 실제 출석 시도 결과 append-only 기록.
   - 실제 provider 호출은 local API route가 담당하고, GUI 스케줄러는 due 실행 요청과 failure-only 알림만 담당한다.


2. host & client: openSSH 의존성을 덜기 위해, host에 sleep/shutdown/restart 제어 기능을 만들고, client가 http 요청을 통해 이것을 제어하도록 구성하여 원격 전원 관리 기능에서 openSSH 의존성을 제거.


3. (experimental)host: 아직도 원인을 알 수 없는 gui 버벅임 현상이나, OBS binding이 꼬이는 문제(OBS에서 기인한 문제일 가능성도 있음) 등을 자체적으로 진단/자동으로 프로세스를 재시작하는 등의 원활한 동작 상태를 유지하기 위한 셀프 안정화 기능 구현, 또는 명확한 원인 진단.


4. host: sidebar 개선 및 기능 개발(호출/숨김 동작 개선 및 편의성 제고, main gui의 기능 일부 이식 등 고려 중).
