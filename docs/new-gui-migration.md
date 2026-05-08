# 새 메인 GUI 마이그레이션 가드레일

## 목표
- Windows 전용 설치형 앱이라는 현재 배포 모델을 유지한다.
- 최종 설치 패키지는 계속 Inno Setup 기반 `HomeworkHelper_*_Setup.exe`로 제공한다.
- Tauri/React는 PyQt 메인 창을 대체할 새 셸로 도입하되, 기능 parity 전까지 기존 PyQt 경로를 제거하지 않는다.

## DB 연속성 원칙
- 사용자 DB 경로는 기존 `%APPDATA%\HomeworkHelper\homework_helper_data\app_data.db`를 유지한다.
- React/Tauri/Rust 코드는 SQLite 파일을 직접 열지 않는다.
- 새 GUI는 `/api/gui/*` facade를 통해서만 상태를 읽거나 명령을 실행한다.
- 스키마 변경은 additive migration만 허용한다.
- 테이블 삭제, DB 재생성, AppData 삭제, installer uninstall 단계의 사용자 데이터 삭제는 금지한다.
- 새 migration 전에는 기존 `backup_database()` 흐름과 별도 샘플 DB 회귀 테스트를 유지한다.

## 기능 보존 체크리스트
- 메인 게임 목록: 이름, 고해상도 아이콘, 진행률, 상태, 실행 버튼.
- 창 동작: 내용 기반 컴팩트 높이, 리사이즈 불가, 직전 위치 복원, 항상 위, 게임 실행 시 숨김.
- 설정: 전역 설정, DPI/앱 스케일, 시작프로그램, 관리자 권한 전환.
- CRUD: 게임 추가/편집/삭제, 웹 바로가기 추가/편집/삭제.
- 런타임: 프로세스 모니터링, 스케줄러, 알림, HoYoLab, 스크린샷, OBS 녹화, 사이드바/오버레이.
- 배포: PyInstaller backend, Tauri shell, Inno Setup installer, 코드 서명, 예약 작업.

## 현재 1차 구현 범위
- `/api/gui/main-state`: 새 GUI가 사용할 읽기 전용 상태 스냅샷.
- `/api/gui/processes/{id}/launch`: 기존 `Launcher`를 통한 실행 명령.
- `src/gui/new_gui/frontend`: Tauri용 React 컴팩트 메인 창 골격.
- `src-tauri`: Tauri v2 셸 스캐폴드.
- `build.py`: 새 메인 GUI frontend 번들을 ignored `build/main-gui-static`에 생성.

## 후속 구조 개선 후보
- `homework_helper.pyw`를 server/bootstrap/legacy-pyqt entrypoint로 분리한다.
- AppData 경로 중복을 `src/utils/common.py` 또는 별도 `app_paths.py`로 통합한다.
- `requirements.txt`를 runtime/dev/windows 빌드 의존성으로 나누거나 `pyproject.toml`로 이동한다.
- `src/gui/main_window.py`의 런타임 로직을 API 서비스 계층으로 이동한다.
- Inno staging 단계를 명시화해 `{app}\homework_helper.exe`, `{app}\backend\...`, `{app}\assets\...` 배치를 테스트한다.

## 기본 패키징 포함

기존 installer의 기본 실행 파일은 계속 `homework_helper.exe`로 유지한다. 다만 새 Tauri shell은 별도 환경변수 없이 항상 패키지에 함께 포함한다.

```powershell
python build.py
```

build.py는 기본 빌드 흐름에서 다음 작업을 수행한다.

1. `npm run tauri:build -- --no-bundle`로 Tauri shell을 생성한다.
2. `src-tauri/target/release/homework-helper-shell.exe`를 `dist/homework_helper/homework_helper_gui.exe`로 복사한다.
3. 코드 서명 대상에 `homework_helper_gui.exe`를 추가한다.
4. Inno Setup은 shell 파일이 존재할 때 시작 메뉴에 `HomeworkHelper 새 GUI 미리보기` 바로가기를 추가하고, 업데이트 중 해당 프로세스도 종료한다.

Tauri shell은 설치 폴더 옆의 `homework_helper.exe --run-server`를 sidecar 백엔드로 실행할 준비가 되어 있다. 따라서 shell을 단독 실행해도 기존 FastAPI/SQLite 경계는 Python 백엔드가 계속 소유한다. 이 구조는 DB 직접 접근을 피하기 위한 중간 전환 단계이며, 기본 바로가기를 새 GUI로 바꾸는 것은 기능 parity 확인 이후에만 진행한다.
