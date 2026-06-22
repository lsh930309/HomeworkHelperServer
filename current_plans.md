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

2. host & remote: 개별 게임별 `프로세스 실행` 인자 전달 opt-in 기능.

   ### 목표

   - 게임별 설정에서 직접 실행 파일을 실행할 때 추가 실행 인자를 함께 전달할 수 있게 한다.
   - host GUI와 remote launch API가 같은 저장값과 같은 적용 규칙을 사용한다.
   - 기본 동작은 기존과 동일하게 유지하고, 사용자가 명시적으로 켠 프로세스에만 인자를 적용한다.
   - 1차 사용 사례는 젠레스 존 제로를 `프로세스 선호` 방식으로 실행할 때 `-use-d3d12`를 함께 전달하는 것이다.

   ### 현재 구조 확인

   - 실행 버튼 흐름은 `src/gui/main_window.py`의 `handle_launch_button_in_row()`에서 `preferred_launch_type`에 따라 실행 대상을 고른 뒤 `Launcher.launch_process(...)`를 호출한다.
   - 실제 실행은 `src/core/launcher.py`의 `Launcher.launch_process(launch_command: str, args: str | list[str] | None = None)`가 담당하며, 실행 대상과 추가 인자를 분리해 받는다.
   - 프로세스 저장 모델은 `ManagedProcess`, `ProcessSchema`, `ProcessCreateSchema`, SQLAlchemy `Process` 모델에 새 실행 인자 필드를 추가한다.
   - 프로세스 추가/편집 UI는 `src/gui/dialogs.py`의 `ProcessDialog`에서 실행 경로, 실행 방식, 직접 실행 인자 opt-in을 저장한다.

   ### v1 범위

   - 인자는 resolved target이 실제 실행 파일/직접 실행 대상인 경우에만 적용한다.
   - `바로가기(.lnk)`, `.url`, 런처 프로토콜, 프리셋 launcher 경로에는 v1에서 인자를 붙이지 않는다.
     - 이유: 각 경로는 OS shell/런처가 해석하며 인자 전달 의미가 불안정하다.
   - remote API도 direct target일 때만 저장된 인자를 적용하며, macOS client는 새 필드를 decode/cache만 한다.
   - 저장 형식은 `launch_args_enabled: bool`과 `launch_args: str`의 두 필드로 둔다.
     - opt-in이 꺼져 있으면 `launch_args` 값이 있어도 실행에 사용하지 않는다.
     - 앞뒤 공백을 trim하고, 빈 문자열은 인자 없음으로 취급한다.
     - 줄바꿈/CR/NUL 문자는 거부하고 최대 길이는 512자로 제한한다.
   - 실행 시에는 경로와 인자를 문자열로 단순 결합하지 않고, Windows에서는 `ShellExecuteW`의 parameter 인자로 분리 전달하는 방향을 우선한다.
     - 비-Windows fallback은 `[launch_path] + parsed_args` 형태의 `subprocess.Popen` 리스트 실행으로 정리한다.

   ### 구현 계획 고정본

   1. 저장 모델 확장
      - `ManagedProcess.__init__`, `from_dict`, `to_dict` 호환 경로에 `launch_args_enabled`, `launch_args`를 추가한다.
      - `src/data/schemas.py`의 process schema와 `src/data/models.py`의 `managed_processes` 테이블 모델에 동일 필드를 추가한다.
      - `src/data/beholder.py` 관리 필드명/검증에 실행 인자 필드를 추가하고, trim 후 빈 문자열은 무시하며 newline/CR/NUL 금지와 512자 제한을 적용한다.

   2. 편집 UI 추가
      - `ProcessDialog`의 실행 방식 섹션 근처에 `직접 실행 인자 사용` checkbox와 인자 입력 field를 추가한다.
      - tooltip에는 “프로세스 선호/직접 실행에만 적용, 바로가기/URL에는 적용 안 됨”을 명시한다.
      - 프리셋 자동 적용 시에는 인자를 자동으로 켜지 않고, 저장된 프로세스 단위 설정만 반영한다.

   3. 실행 대상 결정 로직 정리
      - `handle_launch_button_in_row()`에서 실제 target이 직접 실행 대상인지 판별한다.
      - resolved target이 직접 실행 대상일 때만 `launch_args_enabled`와 `launch_args`를 읽어 `Launcher.launch_process(target, args=...)`로 전달한다.
      - `_launch_with_specific_path(..., use_shortcut=False)` 우클릭 직접 실행도 동일한 인자 적용 규칙을 사용한다.
      - shortcut/launcher fallback으로 실행되는 경우에는 인자를 전달하지 않는다.

   4. remote 실행 경로 반영
      - `/remote/processes/{process_id}/launch`에서 resolved target이 직접 실행 대상이고 launcher mode가 아니면 저장된 인자를 전달한다.
      - audit metadata에는 `launch_args_applied` 여부를 기록한다.
      - remote 상태 revision fingerprint에 `launch_args_enabled`, `launch_args`를 포함해 client cache/refresh가 변경을 감지하게 한다.
      - macOS client 모델은 `launch_args_enabled`, `launch_args`를 decode/cache하되 편집 UI는 v1 범위에서 제외한다.

   5. `Launcher` 인터페이스 확장
      - `launch_process(launch_command: str, args: str | list[str] | None = None)` 형태로 확장한다.
      - Windows `ShellExecuteW` 호출은 `file=launch_command`, `params=args_string_or_none`으로 분리한다.
      - 비-Windows 실행은 `subprocess.Popen([launch_command, *parsed_args])`로 실행한다.
      - `.lnk`, `.url`, protocol 처리 분기는 기존 동작을 유지하고 args가 들어와도 무시하거나 명시적으로 로그만 남긴다.

   6. 테스트 및 검증
      - `ManagedProcess.from_dict`가 기존 데이터에 대해 기본값을 채우는지 테스트한다.
      - schema/model/beholder가 새 필드를 허용하고 위험한 줄바꿈/과도한 길이를 거르는지 테스트한다.
      - `Launcher.launch_process`가 Windows ShellExecute parameter 분리와 비-Windows list 실행을 사용하는지 mock 기반으로 검증한다.
      - `ProcessDialog.get_data()`가 checkbox/input 상태를 정확히 반환하는지 GUI test를 추가한다.
      - `MainWindow`와 remote launch API 실행 흐름에서 direct 실행에는 인자가 전달되고 shortcut/url/launcher 실행에는 전달되지 않는지 단위 테스트를 추가한다.

3. host & client: openSSH 의존성을 덜기 위해, host에 sleep/shutdown/restart 제어 기능을 만들고, client가 http 요청을 통해 이것을 제어하도록 구성하여 원격 전원 관리 기능에서 openSSH 의존성을 제거.


4. (experimental)host: 아직도 원인을 알 수 없는 gui 버벅임 현상이나, OBS binding이 꼬이는 문제(OBS에서 기인한 문제일 가능성도 있음) 등을 자체적으로 진단/자동으로 프로세스를 재시작하는 등의 원활한 동작 상태를 유지하기 위한 셀프 안정화 기능 구현, 또는 명확한 원인 진단.


5. host: sidebar 개선 및 기능 개발(호출/숨김 동작 개선 및 편의성 제고, main gui의 기능 일부 이식 등 고려 중).
