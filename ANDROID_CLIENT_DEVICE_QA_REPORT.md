# Android 클라이언트 실기기 개선/검증 보고서

작성일: 2026-05-17  
대상 기기: Samsung SM-S938N, Android 16, wireless ADB  
대상 앱: `dev.homeworkhelper.remote` 0.1.0

## 구현 요약

1. **연결 상태 robust 처리**
   - Remote Agent URL을 `http://`/`https://` 기준으로 사전 검증하도록 추가했다.
   - 네트워크/인증/URL 오류를 raw 예외 대신 한국어 안내 문구로 표시한다.
   - 새로고침 실패 시 기존 목록이 현재 서버 데이터처럼 보이지 않도록 “마지막 성공 데이터 표시 중” stale 배너와 마지막 동기화 시각을 추가했다.
   - 헤더 상태 점이 offline/auth/stale/partial/success 상태를 우선 반영하도록 수정했다.

2. **Tailscale/페어링 UX 보강**
   - 추천 Tailscale URL 적용 시 서버가 바뀌면 pairing code로 다시 인증해야 함을 명확히 안내한다.
   - 현재 paired live host(`http://100.109.140.97:8000`)는 데이터 보존 설치 후 정상 동기화됨을 확인했다.

3. **다크/라이트 모드 추적**
   - Compose Material3 light/dark color scheme을 명시하고 시스템 테마 변경을 `isSystemInDarkTheme()`로 추적한다.
   - 상태바/내비게이션바 아이콘 대비를 시스템 모드에 맞게 조정했다.
   - 설정 화면과 헤더에 현재 시스템 테마 추적 상태를 표시한다.

4. **GUI 품질 개선**
   - 하단 탭 기호를 의미 있는 아이콘 문자(`⌂`, `▶`, `⛓`, `⚙`)로 교체했다.
   - 탭 전환 시 스크롤 위치가 상단으로 돌아오도록 고정했다.
   - 연결 탭에서 기존 연결/빈 상태를 먼저 보여주고, UsageStats와 새 연결 추가 폼을 분리했다.
   - UsageStats 버튼 줄바꿈 문제를 해결했다.
   - game-link 카드의 `null` 노출을 제거했다.
   - 전원 설정 파일 경로는 파일명 우선 + 상세 경로 1줄 ellipsis로 축약했다.

## 검증 결과

### 내부 검증

- `./.venv/bin/python -m pytest tests/test_remote_android_client_static.py`
  - 결과: 9 passed
- `./.venv/bin/python tools/verify_android_internal.py`
  - Android SDK readiness: passed
  - Gradle `:app:assembleDebug`: BUILD SUCCESSFUL
  - APK artifact contract: passed
  - 최종 결과: Android internal verification passed

### 실기기 보존형 검증

기존 pairing/token을 유지하기 위해 앱 데이터 삭제 없이 `adb install -r` 방식으로 검증했다.

- `./.venv/bin/python tools/smoke_android_remote_controller.py --adb /opt/homebrew/share/android-commandlinetools/platform-tools/adb --device 172.30.1.85:38263 --report-usage-access --require-usage-access`
  - 설치: Success
  - UsageStats: `GET_USAGE_STATS: allow`
  - 앱 실행: passed

- live host 새로고침 검증
  - 표시 메시지: `동기화 완료: 게임 4개, 연결 0개, 모바일 세션 0개, 숏컷 2개`
  - 상태 메시지: `동기화 정상 · 시스템 다크 모드 추적 중`
  - 최종 패치 후 재설치/새로고침: `final_after_last_patch_refresh.png`
  - 앱 PID 기준 logcat 경고/오류: 없음

- 시스템 테마 전환 검증
  - `cmd uimode night no` 후: `시스템 라이트 모드 추적 중`
  - `cmd uimode night yes` 복구 후: `시스템 다크 모드 추적 중`
  - 상태바 아이콘은 라이트/다크 양쪽에서 시각적으로 식별 가능했다.

- URL validation 검증
  - `httrp://bad` 입력 후 새로고침 시 즉시 차단됨.
  - `127.0.0.1`/`10.0.2.2` 같은 ADB reverse 테스트 URL이 끊겼을 때 별도 안내가 나오도록 보강함.
  - 표시 문구: `Remote Agent URL은 http:// 또는 https://로 시작해야 합니다.`
  - 앱 재시작 후 저장된 정상 URL `http://100.109.140.97:8000` 복구 확인.

### macOS 클라이언트 데이터 비교

macOS 클라이언트 캐시와 Android 실기기 게임 탭을 비교했다.

- macOS cache: `/Users/lsh930309/Library/Application Support/HomeworkHelperRemote/cache/processes.json`
- macOS cache process count: 4
- Android UI matched process count: 4
- 일치한 게임:
  - 명조: 워더링 웨이브
  - 승리의 여신: 니케
  - 젠레스 존 제로
  - 붕괴: 스타레일

## 증거 아티팩트

실기기 스크린샷/UI dump/logcat은 아래 디렉터리에 저장했다.

`/private/tmp/hh-android-device-fix-20260517-210220`

주요 파일:

- `theme_light.png` / `theme_dark_restored.png`
- `final_live_refresh.png` / `final_live_refresh_logcat.txt`
- `final_after_last_patch_refresh.png` / `final_after_last_patch_logcat.txt`
- `url_validation_error_2.png`
- `live_settings_path_shortened.png`
- `final_game_compare.png`

## 참고

기존 pairing 상태를 보존하기 위해, 앱 데이터를 삭제하고 임시 서버에 다시 pairing하는 전체 destructive e2e(`tools/verify_android_device.py`)는 이번 최종 실기기 검증에서는 실행하지 않았다. 대신 현재 paired live host 기준으로 설치, 실행, 권한, 새로고침, 테마, URL validation, macOS 데이터 비교를 자동화해서 확인했다.
