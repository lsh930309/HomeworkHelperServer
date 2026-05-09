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
- [ ] GAME-001: 새 GUI에서 게임 추가/편집이 메인 창 내부 modal이 아닌 별도 popup 창으로 열리고, 저장 후 메인 목록이 갱신된다.
- [ ] GAME-002: 바로가기/직접 실행/런처 우선 실행이 동작한다.
- [ ] GAME-002: 새 GUI 실행 실패/성공 안내에 선택된 실행 방식과 실제 대상 경로가 표시된다.
- [ ] WEB-001: 웹 바로가기 클릭/우클릭 편집/삭제/일일 초기화 상태가 동작한다.
- [ ] WEB-001: 새 GUI에서 웹 바로가기 추가/편집이 별도 popup 창으로 열리고, 저장 후 메인 목록이 갱신된다.
- [ ] SETTINGS-001: 새 GUI 설정 popup의 항상 위 옵션이 즉시 반영되고 재시작 후에도 보존된다.
- [ ] APP-001: 새 GUI 메인 창의 GitHub favicon 버튼이 외부 브라우저로 저장소를 연다.
- [ ] APP-001: 새 GUI 메인 목록은 상태 텍스트 열 없이 좌측 행 바/점 인디케이터와 진행률 색상만으로 실행중/완료/미완료 상태를 구분한다.
- [ ] SETTINGS-001: 전역 설정 저장 후 재시작해도 값이 보존된다.
- [ ] SETTINGS-001: 관리자 권한 전환 및 시작프로그램 설정이 동작한다.
- [ ] SETTINGS-001: 새 GUI의 일반/알림/사이드바/스크린샷/녹화/HoYoLab 설정 패널이 각각 별도 popup 창으로 열리고, 창 크기가 콘텐츠에 맞춰져 가로/세로 스크롤바가 생기지 않는다.

## 런타임/데이터 안전

- [ ] SESSION-001: 게임 시작/종료 시 세션이 정상 기록된다.
- [ ] SESSION-001: 게임 종료 시 기록되는 종료 스태미나가 음수/비정상 값이면 Beholder가 저장을 차단한다.
- [ ] SESSION-001: 앱 재시작 후 중복 open session incident에서 “이전 세션 이어가기”가 동작한다.
- [ ] SESSION-001: PC 재부팅/게임 미실행 상황의 open session incident에서 “마지막 앱 실행 시각에 종료”가 동작한다.
- [ ] SESSION-001: 오래된 legacy open session incident에서 “복구 불가 기록 버리기”가 동작한다.
- [ ] BEHOLDER-001: PyQt와 새 GUI 모두 incident를 표시하고, 새 GUI에서는 추천 액션/결과/위험 신호가 사용자 언어로 보이며 선택 액션을 수행한다.
- [ ] BEHOLDER-001: 게임/웹 편집 화면 저장 시 런타임 전용 필드(마지막 플레이, 스태미나, 웹 완료 시각)가 임의로 초기화되지 않는다.
- [ ] BEHOLDER-001: 설정/스태미나 값이 허용 범위를 벗어날 때 저장이 차단되고 사용자에게 어떤 값이 문제인지 표시된다.
- [ ] BEHOLDER-001: 새 GUI Beholder modal의 위험 신호는 내부 코드명 대신 사용자 언어로 표시된다.
- [ ] BEHOLDER-001: 새 저장/편집 기능 추가 시 UI/API route에 직접 db.commit()이 없고 CRUD/Beholder 경계를 통과한다.
- [ ] BACKUP-001: 앱 시작 DB rolling backup과 Beholder 백업 목록/복구 preview가 보인다.
- [ ] BACKUP-001: 복구 preview에 현재 DB/백업의 게임·웹·플레이 기록 수와 복구 영향 안내가 표시된다.
- [ ] HOYOLAB-001: 새 GUI 설정 HoYoLab 탭에서 쿠키 자동 추출/수동 저장/삭제/스태미나 테스트 조회가 동작한다.
- [ ] HOYOLAB-001: 새 GUI 게임 행 우클릭 “스태미나 새로고침”이 현재 스태미나를 DB/진행률에 반영한다.

## PyQt fallback 유지 기능

- [ ] SIDEBAR-001: 게임 실행 시 사이드바 표시/자동 숨김/볼륨/시계/플레이타임이 동작한다.
- [ ] SIDEBAR-001: 새 GUI preview 스마트 서랍 손잡이가 우측 edge에 표시되고 hover/click으로 열리며, Pin 고정/Escape 닫기/자동 숨김/high-DPI 위치 보정이 동작한다.
- [ ] SCHEDULER-001: 필수 접속/주기/수면 보정/일일 리셋/스태미나 알림이 동작한다.
- [ ] SCHEDULER-001: 새 GUI 알림 설정 popup에서 현재 미완료 수와 예정 알림 preview가 실제 상태와 일치한다.
- [ ] SCHEDULER-001: 새 GUI 알림 preview가 알림 종류/남은 시간/심각도/켜짐·꺼짐 상태를 사용자 언어로 표시한다.
- [ ] HOYOLAB-001: PyQt 런타임에서 게임 종료 후 `stamina_at_end` 기록 및 시작/종료 재동기화가 동작한다.
- [ ] SCREENSHOT-001: 새 GUI 키 입력 캡처로 트리거 키 변경 후 게임패드 스크린샷, 저장 폴더, capture mode가 동작한다.
- [ ] RECORDING-001: 새 GUI OBS 설정 불러오기 후 저장, 자동 실행, 녹화 시작/중지, 사이드바 상태 표시가 동작한다.
- [ ] RECORDING-001: 새 GUI 사이드바 서랍에서 최근 녹화 파일 목록이 표시되고 파일 열기가 동작한다.
- [ ] SCREENSHOT-001: 새 GUI 사이드바 서랍에서 최근 스크린샷 썸네일이 표시되고 클릭/복사 버튼이 동작한다.
- [ ] CLIPBOARD-001: 새 GUI/API에서 스크린샷 파일 복사 후 탐색기/채팅창 파일·이미지 붙여넣기가 동작한다.

## 대시보드/분석

- [ ] DASHBOARD-001: 대시보드 열기, 날짜 범위 변경, 게임 필터, calendar, icon 표시가 동작하고 신규 GUI v6 톤앤매너와 공통 --hh-* 버튼/card 색상 token이 일관된다.


## 실사용 데이터 복제 검증

- [ ] 로컬 `HomeworkHelper.zip`이 있는 상태에서 `python tools/verify_project.py --require-real-data`가 통과한다.
- [ ] `python tools/verify_project.py --full --require-real-data`가 새 GUI와 dashboard frontend를 모두 빌드한다.
- [ ] 신규 GUI 미리보기에서 실제 DB 복제본의 게임/웹/아이콘/설정이 표시된다.
