# PyQt6 → PySide6 호스트 앱 마이그레이션 체크리스트

작성일: 2026-05-22
목적: 의존성 리스크를 낮추기 위해 현재 Windows 호스트 앱의 PyQt6 기반 구조를 가능한 한 그대로 유지하면서 PySide6(Qt for Python)로 이전한다.

## 체크 방식 지시사항

- 각 항목은 **실제 변경을 완료하고, 바로 아래 `작업 요약`과 `근거`를 채운 뒤에만** `[x]`로 바꾼다.
- `작업 요약`에는 무엇을 바꿨는지 한두 문장으로 적는다. 예: `PyQt6.QtCore import를 PySide6.QtCore로 교체하고 Signal/Slot 별칭을 적용했다.`
- `근거`에는 재현 가능한 증거를 적는다. 예: `src/gui/main_window.py:23`, `rg -n "PyQt6|pyqtSignal|pyqtSlot" ... 결과 0건`, `pytest tests/test_gui_layout.py -q 통과`, `Windows 수동 스모크: 트레이 토글 확인`.
- 증거가 간접적이거나 불충분하면 체크하지 말고 `근거: 증거 불충분 - ...`로 남긴다.
- 목표는 프레임워크 이전이며 UI/UX 재설계가 아니다. 기존 창/트레이/사이드바/알림/스레드 구조와 사용자 동작 계약을 보존한다.
- 호스트 앱 범위는 `homework_helper.pyw`, `src/gui/**`, PyQt 의존 `src/core/**`, `src/utils/**`, 관련 테스트/빌드/문서다. `remote_clients/macos`, Tauri/React preview 자체는 PyQt6 사용 지점이 아니므로 별도 기능 변경 대상이 아니다.
- Qt for Python 공식 문서 기준으로 PySide6 기본 import는 `from PySide6...`, 시그널/슬롯 데코레이터는 `Signal`/`Slot`이다. PyInstaller는 Qt 의존성을 대체로 분석하지만, Qt 모듈/플러그인 포함 여부는 빌드 산출물로 검증한다.

## 현재 탐색 스냅샷

- `requirements.txt`에는 GUI 의존성으로 `PyQt6` 1건이 있다.
- `homework_helper.spec`의 `hiddenimports`에는 `PyQt6`, `PyQt6.QtWidgets`, `PyQt6.QtCore`, `PyQt6.QtGui`가 명시되어 있다. 현재 코드에는 `QtNetwork`도 사용된다.
- 직접 PyQt6 import가 확인된 활성 소스/테스트 파일:
  - `homework_helper.pyw`
  - `src/core/hoyolab_reconcile.py`
  - `src/core/instance_manager.py`
  - `src/core/notifier.py`
  - `src/core/resource_reconcile.py`
  - `src/gui/beholder_dialog.py`
  - `src/gui/countdown_overlay.py`
  - `src/gui/dialogs.py`
  - `src/gui/gui_notification_handler.py`
  - `src/gui/main_window.py`
  - `src/gui/preset_editor_dialog.py`
  - `src/gui/sidebar/edge_trigger_window.py`
  - `src/gui/sidebar/sidebar_controller.py`
  - `src/gui/sidebar/sidebar_widget.py`
  - `src/gui/sidebar_settings_dialog.py`
  - `src/gui/tray_manager.py`
  - `src/gui/volume_panel.py`
  - `src/utils/clipboard.py`
  - `src/utils/process.py`
  - `tests/test_clipboard.py`
  - `tests/test_gui_layout.py`
- 문서/메타데이터 PyQt6 언급: `README.md`, `docs/architecture.md`, `docs/os_dependencies.md`, `docs/mvp-roadmap.md`, `docs/archive/session-progress-2025-11-14.md`, `docs/archived/architecture-old.md`, `docs/migration-feature-inventory.md`, `docs/migration-smoke-checklist.md`.
- `.ui`, `.qrc`, `.qml`, `.qss` 소스 파일은 현재 저장소 탐색 범위에서 발견되지 않았다.

## 0. 범위 고정 및 사전 기준

- [ ] 현재 PyQt6 참조 목록을 다시 수집하고 이 체크리스트의 탐색 스냅샷과 차이를 반영한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] PySide6 적용 전략을 한 가지로 확정한다: 네이티브 `Signal`/`Slot` 명칭으로 전환하거나, 구조 보존을 위해 `Signal as pyqtSignal`, `Slot as pyqtSlot` 호환 별칭을 일관 적용한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 마이그레이션 범위에서 remote macOS 클라이언트와 Tauri/React preview 기능 변경을 제외하고, 호스트 앱 PyQt6 의존 제거에만 집중한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

## 1. 의존성, 빌드, 패키징

- [ ] `requirements.txt`의 GUI 의존성을 `PyQt6`에서 `PySide6`로 바꾸고, 필요한 경우 버전 하한/상한 정책을 문서화한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 로컬 가상환경/설치 검증에서 `PySide6` import가 가능하고 `PyQt6` 없이도 호스트 앱 import가 가능한지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `homework_helper.spec`의 `hiddenimports`를 `PySide6`, `PySide6.QtWidgets`, `PySide6.QtCore`, `PySide6.QtGui`, `PySide6.QtNetwork` 기준으로 갱신한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] PyInstaller 빌드 로그/산출물에서 Qt platform/image/icon 관련 플러그인이 누락되지 않는지 확인하고, 필요 시 hook/datas 보강을 추가한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `build.py`의 Windows host 빌드 흐름(`build_with_pyinstaller`, release zip, installer 서명/생성)이 PySide6 전환 후에도 그대로 동작하는지 검증한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `installer.iss`와 릴리스 산출물 이름/아이콘/설치 경로 계약이 프레임워크 변경으로 흔들리지 않았는지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

## 2. 앱 엔트리포인트와 수명주기

- [ ] `homework_helper.pyw`의 `QApplication`, `QMessageBox`, `QFontDatabase`, `QFont` import와 `app.exec()` 이벤트 루프를 PySide6 기준으로 이전한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `homework_helper.pyw` 상단 DPI 환경 변수(`QT_ENABLE_HIGHDPI_SCALING`, `QT_SCALE_FACTOR`, `QT_FONT_DPI`)와 사용자 배율 ini 읽기 동작이 기존과 동일한지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 앱 시작/종료 경로에서 API 서버 시작, `stop_api_server()`, `atexit`, signal handler, `QApplication.setQuitOnLastWindowClosed(False)` 계약을 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/core/instance_manager.py`의 `QSharedMemory`, `QLocalServer`, `QLocalSocket`, duplicate-instance activation, stale server removal 경로를 PySide6로 이전하고 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/tray_manager.py`의 `QSystemTrayIcon`, `QMenu`, `QAction`, show/hide toggle, direct quit path를 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

## 3. 메인 윈도우와 일반 GUI 다이얼로그

- [ ] `src/gui/main_window.py`의 QtWidgets/QtCore/QtGui import 전체를 PySide6로 전환하고, `IconDownloader(QThread)` 및 `MainWindow` class-level signal 동작을 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `main_window.py`의 `QTimer`/`QTimer.singleShot`, 메뉴 `QAction`/`QMenu`, `QSettings`, 창 위치/상대 앵커, screen clamp, table sizing 동작을 회귀 검증한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `main_window.py`의 recording/screenshot/gamepad callback relay signal과 sidebar dispatch가 메인 스레드에서 계속 실행되는지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/dialogs.py`의 `_RemoteSettingsWorker(QThread)` signal, `RemoteSettingsDialog`, `ProcessDialog`, `GlobalSettingsDialog`, `WebShortcutDialog`, HoYoLab/Nikke 설정 다이얼로그를 PySide6로 이전한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `dialogs.py`의 `QDialog.exec()`, `QInputDialog`, `QFileDialog`, `QMessageBox`, `QDialogButtonBox.StandardButton`, enum 비교가 PySide6에서도 동일하게 동작하는지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/preset_editor_dialog.py`의 `presets_changed` signal, `QSplitter`, icon preview `QPixmap`, `QTime` parsing, file dialog 경로를 이전한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/beholder_dialog.py`의 action button role 구성과 incident 처리 결과(`dialog.action`)를 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/countdown_overlay.py`의 fullscreen/top-level overlay, `paintEvent`, `QPainter`, `QTimer` 카운트다운 완료 callback을 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/gui_notification_handler.py`의 `QObject`/slot 기반 notification activation relay를 PySide6로 이전한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/volume_panel.py`의 `QRunnable` 저장 worker, `QThreadPool`, volume slider, white-tinted system icons, popover positioning을 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

## 4. 사이드바/오버레이 구조

- [ ] `src/gui/sidebar/edge_trigger_window.py`의 topmost frameless tool window flags, `WA_TranslucentBackground`, `WA_ShowWithoutActivating`, `WindowTransparentForInput`, cursor polling, handle geometry를 PySide6로 이전한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `EdgeTriggerWindow.paintEvent()`의 direct paint path, borderless stylesheet, hover/cooldown/auto-hide handle 계약을 회귀 검증한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/sidebar/sidebar_controller.py`의 screen selection, primary screen fallback, settings application, active-game/always/disabled mode 상태 전이를 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/sidebar/sidebar_widget.py`의 `QPropertyAnimation`, `QEasingCurve`, slide in/out geometry, auto-hide/playtime/clock/recording/cursor timers를 PySide6로 이전한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `sidebar_widget.py`의 thumbnail loaders(`QRunnable`, `QThreadPool`, signal payload object), video placeholder paint, hover thumbnail 확대, QPixmap/QImage 변환을 검증한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `sidebar_widget.py`의 screenshot/recording context menus, clipboard copy/delete, `QMetaObject.invokeMethod`, `pyqtSlot` 대상 메서드를 PySide6 Slot/호환 별칭 기준으로 정리한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/gui/sidebar_settings_dialog.py`의 `QMetaObject.invokeMethod`, `Q_ARG`, key capture callback, `_on_trigger_captured`, `_on_trigger_timeout` queued connection 경로를 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

## 5. Qt 기반 core/util 모듈

- [ ] `src/core/hoyolab_reconcile.py`의 `QObject`, `QRunnable`, `QThreadPool`, `QTimer`, fetch/persist signal, slot 메서드를 PySide6로 이전한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/core/resource_reconcile.py`의 Nikke resource fetch/persist worker와 lifecycle-token/request-seq 기반 stale result 차단 로직을 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/core/notifier.py`의 `NotificationSignalBridge` signal이 Windows toast callback 백그라운드 스레드에서 GUI 메인 스레드로 안전하게 전달되는지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/utils/clipboard.py`의 `QMimeData`, `QUrl`, `QImage`, `QBuffer`, `QIODevice`, `QApplication.clipboard()` fallback과 Windows native clipboard 경로를 이전한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `src/utils/process.py`의 `QFileIconProvider`, `QFileInfo`, `QIcon`, `QPixmap`, high-DPI icon cache fallback을 보존한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

## 6. 테스트와 정적 검증

- [ ] `tests/test_gui_layout.py`와 `tests/test_clipboard.py`의 PyQt6 imports를 PySide6 기준으로 갱신하고 `QT_QPA_PLATFORM=offscreen` 테스트 부트스트랩을 유지한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] PyQt6 문자열을 직접 기대하는 테스트/정책/문서 검증이 있다면 PySide6 전환 목적에 맞게 기대값을 업데이트한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 최소 정적 검증으로 PyQt 의존 파일 전체를 `py_compile`하거나 import smoke하여 PySide6 import 오류가 없는지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 핵심 단위 테스트를 실행한다: `pytest tests/test_gui_layout.py tests/test_clipboard.py tests/test_build_release.py tests/test_dashboard_static_build.py`.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 가능하면 전체 pytest를 실행하고, OS 제한으로 실패하는 항목은 실패 원인과 마이그레이션 관련성을 분리해 기록한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `rg -n "PyQt6|pyqtSignal|pyqtSlot|pyqtProperty"`를 실행해 활성 소스/테스트/빌드 파일에서 잔여 PyQt6 API가 없는지 확인한다. 보존해야 할 문서 언급은 별도로 정리한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

## 7. Windows 호스트 수동 스모크

- [ ] Windows에서 `python homework_helper.pyw` 또는 패키지 실행 파일로 호스트 앱을 시작하고 메인 창, 폰트, DPI 배율, API 서버 health가 정상인지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 중복 실행 시 기존 인스턴스 활성화(`QSharedMemory`/`QLocalServer`)와 경고 메시지 경로를 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 시스템 트레이 상주, 창 숨김/복원, 직접 종료, 마지막 창 닫힘 후 앱 유지 동작을 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 메인 게임 테이블, 프로세스 추가/편집/삭제, 웹 바로가기 추가/편집/삭제, 리모트 설정, 전역 설정, 자원 추적 설정 다이얼로그를 빠르게 순회한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 사이드바 `항상 사용`/`게임 중에만 사용`/`사용 안함`, edge handle auto-hide, slide-in/out, 볼륨, 스크린샷/녹화 섹션을 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 스크린샷 파일 복사/이미지 클립보드, OBS 녹화 카운트다운 overlay, 게임패드 long-press relay가 가능한 환경에서 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] Windows toast notification activation이 `NotificationSignalBridge`를 통해 기존 callback으로 전달되는지 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

## 8. 문서, 정리, 완료 판정

- [ ] `README.md`의 badge/기술 스택/설치 설명을 PySide6 기준으로 갱신한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `docs/architecture.md`, `docs/os_dependencies.md`, `docs/mvp-roadmap.md`의 현재 문서 PyQt6 언급을 PySide6로 갱신하거나 역사적/archived 문서로 명확히 남긴다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] `docs/migration-feature-inventory.md`와 `docs/migration-smoke-checklist.md`처럼 현재 기본 GUI를 가리키는 문서는 PySide6 이전 이후의 실제 기본 GUI 명칭과 검증 상태로 갱신한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] archived 문서의 역사적 PyQt6 언급은 현재 동작과 혼동되지 않도록 필요 시 “과거 기록”임을 남기고, 활성 문서의 PyQt6 표기는 제거한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 마이그레이션 완료 판정 전에 `git diff --check`, PyQt/PySide 참조 검색, 의존성 설치 검증, 테스트 결과, Windows/패키징 스모크 근거를 한곳에 모아 최종 요약한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_

- [ ] 최종 변경은 기능 리팩터링이 아니라 PyQt6 → PySide6 이전 범위에 머물렀는지 코드 리뷰 관점으로 확인한다.
  - 작업 요약: _TODO_
  - 근거: _TODO_
