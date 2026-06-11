# 2026-06-10 기준, 현재 추가를 고려하고 있는 기능 정리

## rough idea
- 각 항목당 각각 브랜치 하나를 할당하여 개발 후 main에 머지하는 과정을 마친 후 다음 순서의 작업을 진행할 것임.
- 현재는 간단한 아이디어만 적어둔 상태로, 현재 문서에 각각의 항목에 대한 구체적인 작업 내용을 한 번에 하나씩 정리해 나갈 예정.

---

1. host: hoyolab/blablalink 자동 출석체크 기능 만들기.

   ### 현재까지 합의한 v1 방향

   - 기능 카테고리는 `자동 출석체크`로 하나로 묶되, UI에서는 게임별 row로 분리해서 보여준다.
   - 사용자가 provider/API route를 직접 고르지 않도록 한다. 등록된 게임을 기준으로 시스템 내부에서 조용히 provider와 route를 매핑한다.
     - HoYoLAB 계열 게임 → HoYoLAB daily reward/check-in API
     - NIKKE → BlablaLink daily check-in/points/task API
   - 현재 기본 프리셋 기준으로 우선 UI에 노출할 대상은, 호스트에 등록되어 있고 자동 출첵 매핑이 명확한 게임만으로 제한한다.
     - 우선 후보: `honkai_starrail`, `zenless_zone_zero`, `nikke`
     - HoYoLAB 자체는 Genshin / Honkai Star Rail / Zenless Zone Zero / Honkai Impact 3rd / Tears of Themis 5종 route를 내부적으로 준비할 수 있지만, v1 UI에서는 현재 호스트 앱에 등록된 게임만 보여준다.
   - 기존 스태미나/리소스 추적 기능과는 분리한다.
     - 기존 HoYoLAB/BlablaLink 쿠키 저장 및 추출 기능은 재사용한다.
     - 자동 출첵 설정/상태/히스토리는 별도의 관리 다이얼로그 또는 탭에서 관리한다.
   - 자동화 엔진은 브라우저 의존이 없는 direct API call 방식을 최우선으로 한다.
     - HoYoLAB은 현재 사용 중인 HoYo.Daily 확장 프로그램처럼 API 호출 기반 구현을 우선한다.
     - BlablaLink도 우선 기존 `NikkeConfig` 쿠키와 웹 번들에서 확인되는 task/points/check-in API route를 사용해 direct API 가능성을 검증한다.
     - direct API가 막히거나 지나치게 불안정할 때만 headless browser / Playwright / Tampermonkey 계열 fallback을 검토한다.
   - 자동 실행은 HomeworkHelper host 앱이 실행 중일 때만 보장한다.
     - 앱 시작 시 missed/catch-up 실행을 수행한다.
     - 앱 실행 중에는 provider별 고정 reset time 이후 자동 시도한다.
     - Windows 작업 스케줄러 등 OS-level always-on job은 v1 범위에서 제외한다.
   - reset time은 사용자 설정값이 아니라 서비스 고정값으로 취급한다.
     - HoYoLAB: KST 01:00
     - BlablaLink: KST 09:00
   - 알림 정책은 `실패만 알림`을 기본으로 한다.
     - 성공/이미 완료는 조용히 기록만 남긴다.
     - 인증 만료, 캡차/위험감지, route 변경, 네트워크 실패 등 사용자 조치가 필요한 실패만 알림으로 표시한다.

   ### 구현 전 검증 계획 고정

   실제 출석 처리 POST는 계정 상태에 영향을 줄 수 있으므로, 검증 단계에서는 읽기 전용 probe만 수행한다.

   1. HoYoLAB read-only probe
      - 저장된 HoYoLAB 쿠키가 있는지 확인한다.
      - `genshin.py`를 통해 daily reward 상태 조회가 가능한지 확인한다.
      - `claim_daily_reward()` 또는 `/sign` 성격의 실제 출석 POST는 검증 단계에서 호출하지 않는다.
      - 성공 기준:
        - 저장 쿠키로 로그인/보상 상태를 읽을 수 있음.
        - 이미 출석/미출석 상태를 구현 단계에서 판별할 수 있을 만큼 응답 구조가 확인됨.

   2. BlablaLink read-only probe
      - 저장된 `NikkeConfig` 쿠키로 로그인 상태를 확인한다.
      - 대표 계정/서버 정보를 기존 방식으로 확인한다.
      - BlablaLink 웹 번들에서 확인한 task/points/check-in 관련 route 중 읽기 성격의 endpoint를 우선 조사한다.
        - 예: task list/status, points/status, user collection 등
      - `DailyCheckIn` 등 실제 출석 POST는 검증 단계에서 호출하지 않는다.
      - 성공 기준:
        - 기존 쿠키/헤더 구조로 출석 또는 task 상태를 읽을 수 있음.
        - 구현 단계에서 하루 1회 실행 여부와 이미 완료 상태를 판별할 수 있는 신뢰 가능한 응답이 확인됨.

   3. 앱 통합 가능성 probe
      - 현재 등록된 게임 목록에서 자동 출첵 provider/route 매핑이 가능한 항목만 추려낼 수 있는지 확인한다.
      - 별도 자동 출첵 관리 다이얼로그/탭에서 다음 정보를 표시할 수 있게 상태 모델을 설계한다.
        - 게임명
        - provider는 내부값으로만 유지
        - 자동 출첵 활성 여부
        - 마지막 시도 시각
        - 마지막 결과: success / already_done / auth_required / challenge_required / network_error / route_error 등
        - 다음 예정 시각
      - 실행 결과는 local 상태로 기록하고, 성공/이미 완료는 조용히 히스토리에만 남기는 방향으로 설계한다.

   ### 2026-06-11 읽기 전용 검증 결과

   검증 단계에서는 계정 상태를 바꿀 수 있는 실제 출석 처리 POST를 호출하지 않았다.

   1. 로컬 환경/인증 상태
      - `.venv`에 `genshin` 패키지가 설치되어 있으며, `Client.get_reward_info()`, `Client.get_monthly_rewards()`, `Client.claim_daily_reward()` API가 존재함을 확인했다.
      - 현재 macOS 검증 환경에서는 Windows DPAPI가 없어 `HoYoLabConfig`/`NikkeConfig` 복호화가 불가능하다.
      - 현재 macOS의 실제 HomeworkHelper 설정 경로에는 `hoyolab_credentials.enc`, `nikke_blabla_credentials.enc` 파일이 없었다.
      - 따라서 이 환경에서 저장 쿠키를 사용한 authenticated live 상태 조회는 수행하지 못했고, Windows host의 실제 저장 세션으로 한 번 더 read-only probe가 필요하다.

   2. HoYoLAB direct API 가능성
      - 참고 확장 프로그램 `Axyss/HoYo.Daily`의 현재 소스는 브라우저 alarm/background script에서 HoYoLAB daily reward API를 직접 `fetch`하는 구조임을 확인했다.
      - `claimable.ts` 기준으로 Genshin / Honkai Star Rail / Zenless Zone Zero / Honkai Impact 3rd / Tears of Themis의 `sign` 및 `info` 계열 endpoint가 분리되어 있다.
      - `genshin.Game` enum에도 `GENSHIN`, `HONKAI`, `STARRAIL`, `ZZZ`, `TOT`가 존재한다.
      - 쿠키 없이 `get_monthly_rewards()`는 5개 게임 모두 보상표 조회에 성공했고, `get_reward_info()`는 `InvalidCookies [-100] Not logged in` 계열 오류를 반환했다.
      - 결론: direct API 구현 가능성은 높음. v1 구현은 `get_reward_info()`로 이미 출석/미출석 상태를 먼저 읽고, 실제 `claim_daily_reward()`는 자동 실행 경로에서만 별도로 호출하도록 분리한다.

   3. BlablaLink direct API 가능성
      - `https://www.blablalink.com/nikke/`의 현재 웹 번들에서 다음 route/method 구조를 확인했다.
        - `GetTaskListWithStatusV2`: GET, `/lip/proxy/lipass/Points/GetTaskListWithStatusV2`
        - `GetTaskListV2`: GET, `/lip/direct/lipass/Points/GetTaskListV2`
        - `GetUserTotalPoints`: GET, `/lip/proxy/lipass/Points/GetUserTotalPoints`
        - `DailyCheckIn`: POST, `/lip/proxy/lipass/Points/DailyCheckIn`
      - 쿠키 없이 읽기 endpoint만 호출한 결과:
        - `GetTaskListWithStatusV2`: HTTP 200, `code=300001`, `msg="game not login"`
        - `GetTaskListV2`: HTTP 200, `code=0`, `data.tasks` 존재
        - `GetUserTotalPoints`: HTTP 200, `code=300001`, `msg="game not login"`
      - 결론: daily check-in POST route는 존재하지만, v1 구현 전에는 기존 `NikkeConfig` 저장 쿠키로 `GetTaskListWithStatusV2`/`GetUserTotalPoints`가 로그인 상태에서 어떤 응답 구조를 반환하는지 Windows host에서 한 번 더 확인해야 한다.

      추가 심화 조사 결과:
      - BlablaLink 웹앱의 task helper는 `getTasks(is_logged_in_or_status_enabled)` 형태로 동작한다.
        - 상태가 필요 없는 public task list: `GetTaskListV2`
        - 로그인/바인딩 상태가 필요한 task status list: `GetTaskListWithStatusV2`
      - 현재 public task list에서 확인되는 NIKKE 일일 task:
        - `task_id="15"`, `task_type=1`, `task_name="매일 출석 체크"`, `points=100`
        - `task_id="14"`, `task_type=2`, `task_name="[매일] 게임 시작"`, `points=100`
      - 프론트엔드 enum 기준 task type은 다음처럼 해석된다.
        - `1`: `DailyCheckIn`
        - `2`: `GameLogin`
        - `3`: `Shop`
        - `4`: `ShareProduction`
        - `5`: `SocialMediaAttention`
      - 프론트엔드의 daily check-in 실행 로직은 다음 흐름이다.
        - reward task를 `reward_infos[0]`와 병합하여 `is_completed`, `completed_times`, `need_completed_times`, `points`를 top-level처럼 사용한다.
        - task type이 `DailyCheckIn`이 아니면 daily check-in 실행 로직을 타지 않는다.
        - `is_completed`가 이미 true면 출첵을 다시 시도하지 않고 "내일 다시 확인" 성격으로 처리한다.
        - 미완료면 `/DailyCheckIn` POST에 `{task_id}`를 전달한다.
        - POST 에러 `1001009`는 프론트엔드에서 사실상 already-done 계열로 처리한다.
        - POST 에러 `300001`은 로그인/게임 로그인 필요 계열로 처리한다.
      - daily task refresh 안내 컴포넌트는 `utc().startOf("day").local().format("HH:mm")`를 사용하므로, KST 환경에서는 `09:00` reset으로 해석된다.

      BlablaLink v1 상태 판별 규칙 초안:
      - `GetTaskListWithStatusV2`를 read-only status probe의 주 endpoint로 사용한다.
      - `code=300001` 또는 `msg="game not login"` 계열은 `auth_required` 또는 `game_login_required`로 정규화한다.
      - 응답에서 `task_type == 1`인 task를 우선 daily check-in task로 판별한다.
        - fallback으로 `task_id == "15"` 또는 task name에 `출석`/`check` 계열 문자열이 있는지 확인한다.
      - `is_completed == true`이면 `already_done`.
      - `reward_infos[0].is_completed == true` 또는 `completed_times >= need_completed_times`이면 `already_done`.
      - daily task가 존재하지만 완료 상태가 아니면 `ready`.
      - daily task를 찾지 못하면 `route_error`.
      - 실제 `/DailyCheckIn` POST는 status probe/test에서는 호출하지 않고, 별도 `perform_check_in` 경로에서만 `{task_id}`로 호출한다.

   4. 앱 통합 매핑 가능성
      - 현재 기본 프리셋 기준 자동 출첵 후보는 다음 3개로 정리 가능하다.
        - `honkai_starrail` → 내부 provider `hoyolab`
        - `zenless_zone_zero` → 내부 provider `hoyolab`
        - `nikke` → 내부 provider `nikke_blablalink`
      - `endfield`, `wuwa`는 현재 자동 출첵 provider 매핑이 없으므로 v1 UI에는 노출하지 않는다.

   5. 다음 검증/구현 고정 사항
      - 실제 계정 세션이 있는 Windows host에서 read-only probe를 한 번 더 실행한다.
      - HoYoLAB은 `get_reward_info()` 응답 파싱을 먼저 구현하고, `claim_daily_reward()` 호출은 명시적인 check-in 실행 경로에만 둔다.
      - BlablaLink는 `GetTaskListWithStatusV2`/`GetUserTotalPoints` 응답 파싱을 먼저 구현하고, `/DailyCheckIn` POST는 자동 실행 단계까지 테스트에서 제외한다.
      - 실패 상태는 `auth_required`, `challenge_required`, `already_done`, `network_error`, `route_error` 등으로 정규화한다.

   ### v1 구현 단계 초안

   1. 검증 probe 추가
      - HoYoLAB daily reward 상태 read-only probe 작성
      - BlablaLink task/points/status read-only probe 작성
      - 실제 출석 POST는 코드상에서도 별도 opt-in 또는 명시적 실행 경로로 분리

   2. provider abstraction 추가
      - 게임별 자동 출첵 대상 descriptor 정의
      - provider별 `status/readiness/check-in` 인터페이스 분리
      - route/provider 세부 정보는 UI에서 숨김

   3. 설정/상태 저장 추가
      - 게임별 자동 출첵 활성 여부 저장
      - 마지막 시도/결과/오류 메시지/다음 예정 시각 기록
      - 기존 스태미나/리소스 추적 필드와 섞지 않음

   4. 스케줄러/코디네이터 추가
      - host 앱 시작 시 catch-up
      - 앱 실행 중 provider reset time 이후 1회 실행
      - 중복 실행 방지 lock 적용
      - 실패만 notifier로 전달

   5. 별도 관리 UI 추가
      - 등록된 게임 중 자동 출첵 매핑이 가능한 게임만 표시
      - 게임별 checkbox, 마지막 결과, 다음 예정 시각 표시
      - 수동 `상태 확인` 버튼은 읽기 전용 probe를 호출
      - 실제 `지금 출첵` 버튼은 구현 후 별도 안전장치/확인 문구를 붙여 검토

   6. 테스트 및 검증
      - provider route mapping 정적 테스트
      - HoYoLAB/BlablaLink 응답 파싱 unit test
      - scheduler catch-up/중복 방지 테스트
      - GUI layout/static test
      - 실제 출석 POST는 수동 승인 전 자동 테스트에서 제외

   ### 2026-06-11 dev-daily-checkin 1차 구현 범위

   이번 브랜치의 첫 구현은 실제 자동 출석 실행이 아니라, Windows host의 저장 세션으로 실동작 여부를 확인하기 위한 BlablaLink/NIKKE 읽기 전용 probe에 한정한다.

   - `NikkeService.get_daily_checkin_status()`를 추가한다.
     - `GET /lip/proxy/lipass/Points/GetTaskListWithStatusV2`만 호출한다.
     - `get_top=false`에서 daily task를 찾지 못하면 `get_top=true`로 한 번 더 읽기 전용 fallback을 수행한다.
     - `/lip/proxy/lipass/Points/DailyCheckIn` POST는 호출하지 않는다.
     - `task_type == 1`을 daily check-in task의 1차 판별 기준으로 삼고, `task_id == "15"` 또는 task name의 `출석`/`check` 문자열을 fallback으로 사용한다.
     - `reward_infos[0]`를 task top-level 값과 병합해 `is_completed`, `completed_times`, `need_completed_times`, `points`를 파싱한다.
     - 결과 상태는 `ready`, `already_done`, `auth_required`, `game_login_required`, `network_error`, `route_error`로 정규화한다.
   - 기존 HoYoLab/BlablaLink 인증 설정 다이얼로그에 임시 실험 버튼 `출석 상태 확인 (읽기 전용)`을 추가한다.
     - 버튼은 NIKKE/BlablaLink 상태만 확인한다.
     - UI 문구에 실제 출석 체크를 실행하지 않았음을 명시한다.
     - 기존 `쿠키 유효성 확인` 흐름에도 BlablaLink 출석 상태 probe 결과를 함께 표시한다.
   - 테스트는 다음을 고정한다.
     - read-only probe가 GET status endpoint만 호출하고 POST를 호출하지 않는지 확인한다.
     - `ready`/`already_done`/`game_login_required`/`auth_required` 상태 정규화와 `get_top=true` fallback을 검증한다.
     - GUI 정적 테스트는 기존 레이아웃 회귀가 없는지 확인한다.
   - 아직 포함하지 않는다.
     - 실제 출석 실행 POST
     - 스케줄러/catch-up/히스토리 저장
     - 별도 자동 출석 관리 다이얼로그
     - HoYoLAB daily reward status 구현

   다음 단계는 실제 BlablaLink 로그인 토큰이 저장된 Windows host에서 위 read-only probe 버튼을 눌러 `GetTaskListWithStatusV2`의 인증 상태 응답을 확인하고, 그 결과에 따라 `ready`/`already_done` 판별 신뢰도를 확정하는 것이다.

   ### 2026-06-11 host 실험 후속

   - Windows host의 실제 BlablaLink 저장 세션에서 임시 `출석 상태 확인 (읽기 전용)` 버튼이 동작함을 확인했다.
     - 관찰 결과: `BlablaLink 출석: 오늘 출석 체크 가능 (task=15, +100P)`
     - 의미: 기존 `NikkeConfig` 쿠키와 `GetTaskListWithStatusV2` read-only route만으로 daily check-in task 상태를 판별할 수 있다.
   - 같은 화면에 HoYoLAB 실제 POST 검증용 임시 버튼을 추가한다.
     - 버튼명: `출석 실행 (붕스→젠존제)`
     - 실행 순서: `honkai_starrail` → `zenless_zone_zero`
     - 구현 방식: `genshin.py`의 `claim_daily_reward(game=..., lang="ko-kr")`를 순차 호출한다.
     - 이 버튼은 read-only probe가 아니라 실제 HoYoLAB daily reward sign POST를 수행한다.
     - 결과 상태는 `success`, `already_done`, `auth_required`, `challenge_required`, `network_error`, `unavailable`, `unsupported`로 정규화한다.
   - 아직 자동 실행/스케줄러로 연결하지 않는다. 이 버튼은 host 실험을 위한 임시 수동 실행 진입점이다.


2. host & client: openSSH 의존성을 덜기 위해, host에 sleep/shutdown/restart 제어 기능을 만들고, client가 http 요청을 통해 이것을 제어하도록 구성하여 원격 전원 관리 기능에서 openSSH 의존성을 제거.


3. (experimental)host: 아직도 원인을 알 수 없는 gui 버벅임 현상이나, OBS binding이 꼬이는 문제(OBS에서 기인한 문제일 가능성도 있음) 등을 자체적으로 진단/자동으로 프로세스를 재시작하는 등의 원활한 동작 상태를 유지하기 위한 셀프 안정화 기능 구현, 또는 명확한 원인 진단.


4. host: sidebar 개선 및 기능 개발(호출/숨김 동작 개선 및 편의성 제고, main gui의 기능 일부 이식 등 고려 중).
