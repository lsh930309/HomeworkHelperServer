# Windows 마이그레이션 Smoke Checklist

자동 테스트로 검증하기 어려운 Windows 전용 기능을 새 GUI 전환 전 수동 확인한다. 각 항목은 `tests/migration/feature_matrix.json`의 Feature ID와 연결된다.

## 앱/패키징

- [ ] APP-001: 설치 후 기본 `HomeworkHelper` 바로가기는 PyQt 앱을 실행한다.
- [ ] APP-001: `HomeworkHelper 새 GUI 미리보기` 바로가기는 `homework_helper_gui.exe`를 실행한다.
- [ ] APP-002: 새 GUI 두 번째 실행 시 새 인스턴스가 뜨지 않고 기존 창이 활성화된다.
- [ ] APP-002: 새 GUI 닫기 버튼이 트레이 숨김으로 동작한다.
- [ ] APP-002: 새 GUI 트레이 메뉴 열기/숨기기/종료가 정상 동작한다.
- [ ] APP-002: PyQt 기본 앱의 기존 단일 인스턴스/트레이 동작이 유지된다.
- [ ] BUILD-001: `python build.py`만으로 새 GUI shell이 installer에 포함된다.

## 게임/웹/설정

- [ ] GAME-001: PyQt와 새 GUI에서 게임 추가/편집/삭제가 같은 DB에 반영된다.
- [ ] GAME-002: 바로가기/직접 실행/런처 우선 실행이 동작한다.
- [ ] WEB-001: 웹 바로가기 클릭/우클릭 편집/삭제/일일 초기화 상태가 동작한다.
- [ ] SETTINGS-001: 전역 설정 저장 후 재시작해도 값이 보존된다.
- [ ] SETTINGS-001: 관리자 권한 전환 및 시작프로그램 설정이 동작한다.

## 런타임/데이터 안전

- [ ] SESSION-001: 게임 시작/종료 시 세션이 정상 기록된다.
- [ ] SESSION-001: 앱 재시작 후 중복 open session incident에서 “이전 세션 이어가기”가 동작한다.
- [ ] SESSION-001: PC 재부팅/게임 미실행 상황의 open session incident에서 “마지막 앱 실행 시각에 종료”가 동작한다.
- [ ] SESSION-001: 오래된 legacy open session incident에서 “복구 불가 기록 버리기”가 동작한다.
- [ ] BEHOLDER-001: PyQt와 새 GUI 모두 incident를 표시하고 선택 액션을 수행한다.
- [ ] BACKUP-001: 앱 시작 DB rolling backup과 Beholder 백업 목록/복구 preview가 보인다.
- [ ] HOYOLAB-001: 새 GUI 설정 HoYoLab 탭에서 쿠키 자동 추출/수동 저장/삭제/스태미나 테스트 조회가 동작한다.
- [ ] HOYOLAB-001: 새 GUI 게임 행 우클릭 “스태미나 새로고침”이 현재 스태미나를 DB/진행률에 반영한다.

## PyQt fallback 유지 기능

- [ ] SIDEBAR-001: 게임 실행 시 사이드바 표시/자동 숨김/볼륨/시계/플레이타임이 동작한다.
- [ ] SIDEBAR-001: 새 GUI preview 스마트 서랍 손잡이가 우측 edge에 표시되고 hover/click으로 열리며, Pin 고정/Escape 닫기/자동 숨김/high-DPI 위치 보정이 동작한다.
- [ ] SCHEDULER-001: 필수 접속/주기/수면 보정/일일 리셋/스태미나 알림이 동작한다.
- [ ] HOYOLAB-001: PyQt 런타임에서 게임 종료 후 `stamina_at_end` 기록 및 시작/종료 재동기화가 동작한다.
- [ ] SCREENSHOT-001: 새 GUI 키 입력 캡처로 트리거 키 변경 후 게임패드 스크린샷, 저장 폴더, capture mode가 동작한다.
- [ ] RECORDING-001: 새 GUI OBS 설정 불러오기 후 저장, 자동 실행, 녹화 시작/중지, 사이드바 상태 표시가 동작한다.
- [ ] CLIPBOARD-001: 새 GUI/API에서 스크린샷 파일 복사 후 탐색기/채팅창 파일·이미지 붙여넣기가 동작한다.

## 대시보드/분석

- [ ] DASHBOARD-001: 대시보드 열기, 날짜 범위 변경, 게임 필터, calendar, icon 표시가 동작한다.


## 실사용 데이터 복제 검증

- [ ] 로컬 `HomeworkHelper.zip`이 있는 상태에서 `python tools/verify_project.py --require-real-data`가 통과한다.
- [ ] 신규 GUI 미리보기에서 실제 DB 복제본의 게임/웹/아이콘/설정이 표시된다.
