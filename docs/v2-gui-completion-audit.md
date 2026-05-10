# v2 GUI Completion Audit

작성일: 2026-05-10  
Current-device status: **Achieved** — 자동 검증 가능한 구현/문서/테스트/빌드 gate가 통과했고, 현재 macOS 기기에서 실행 불가능한 Windows-only 항목은 `docs/v2-gui-windows-logic-review.md`의 코드 비교로 대체 검토했다.

Project migration parity status: **Not achieved yet** — Windows-only smoke가 남아 있어 release/parity gate로는 완료 표시하지 않는다.

## Current-device user scope

2026-05-10 사용자 지시에 따라, 현재 macOS 기기에서 판단 불가능한 Windows-only manual smoke는 이 스레드의 **current-device goal acceptance**에서는 제외한다. 따라서 아래 자동 검증 가능한 v2 구현/문서/테스트/빌드 산출 조건은 current-device scope에서 완료로 판단할 수 있다.

단, 이 예외는 project verification contract의 **migration parity declaration**을 대체하지 않는다. `docs/migration-smoke-checklist.md`의 Windows-only smoke는 release/parity gate로 계속 추적되며, Windows runtime 또는 동등한 검증 artifact 없이 “migration parity 완료”라고 선언하지 않는다.

## Objective를 concrete deliverables로 환산

1. **Requirement 1 — v1/v2 기능 1:1 대응**
   - Evidence:
     - `src/gui/v2/main_window.py`: `V2MainWindow(MainWindow)`가 v1 `MainWindow`를 기능 substrate로 상속한다.
     - `docs/v2-gui-feature-parity.md`: 18개 Feature ID별 v1/v2 구현, 자동 테스트, 잔여 smoke를 매핑한다.
     - `tests/test_migration_feature_matrix.py::test_v2_parity_audit_tracks_every_feature_id_and_smoke_gate`: parity 문서가 `tests/migration/feature_matrix.json`의 모든 Feature ID를 추적하는지 검증한다.
   - Gap:
     - release/parity gate 기준으로는 `docs/migration-smoke-checklist.md`의 Windows runtime 항목이 수동 미실행 상태다. current-device scope에서는 `docs/v2-gui-windows-logic-review.md` 코드 비교로 대체한다.

2. **Requirement 2 — `new-gui-design-philosophy-pyqt-portability-report.md`의 의사결정 반영**
   - Evidence:
     - `new-gui-design-philosophy-pyqt-portability-report.md`: OS titlebar 유지, QSS token/card/topbar/banner, 단일 설정 popup, status visual signal 등의 권장 방향.
     - `src/gui/v2/main_window.py`: `FramelessWindowHint` 제거로 OS 기본 제목 표시줄 유지, topbar/card shell/status indicator/message banner 적용.
     - `src/gui/v2/settings_dialog.py`: 단일 settings hub tab 구조.
   - Gap:
     - release/parity gate 기준으로는 실제 Windows 이동/resize/titlebar/tray smoke가 필요하다. current-device scope에서는 `docs/v2-gui-windows-logic-review.md` 코드 비교로 대체한다.

3. **Requirement 3 — prototype 디자인 철학 보존 + gradient 최소화 + light/dark 개선**
   - Evidence:
     - `src/gui/v2/theme.py`: light/dark `V2Palette`, card/topbar/banner/table/progress QSS.
     - `tests/test_v2_gui_mode.py::test_v2_theme_uses_light_dark_tokens_without_background_gradients`: `linear-gradient`/`radial-gradient` 미사용 검증.
     - `tests/test_v2_gui_mode.py::test_v2_settings_hub_uses_v2_theme_tokens_standalone`: 설정 popup standalone light/dark token 적용 검증.
   - Gap:
     - release/parity gate 기준으로는 실제 Windows DPI/OS theme visual smoke가 필요하다. current-device scope에서는 `docs/v2-gui-windows-logic-review.md` 코드 비교로 대체한다.

4. **Requirement 4 — 매끄럽고 robust하며 빠르고 직관적인 v2 UX**
   - Evidence:
     - `src/gui/v2/main_window.py`: v1 runtime을 재사용해 CRUD/API/Beholder/Sidebar/Tray/Session/Notifier boundary를 유지하고 UI만 v2 shell로 이식.
     - `V2StatusBanner`: 긴 메시지 요약 + 자세히 보기.
     - `tests/test_v2_gui_mode.py::test_v2_status_banner_uses_summary_and_progressive_detail`.
     - `tests/test_v2_gui_mode.py::test_v2_status_banner_ignores_stale_auto_hide_timers`.
     - `SettingsDialogV2`: general/sidebar/HoYoLab 설정을 단일 hub로 묶고 HoYoLab in-place save/Apply를 보장.
     - `tests/test_v2_gui_mode.py::test_v2_hoyolab_tab_saves_credentials_in_place`.
     - `tests/test_v2_gui_mode.py::test_v2_settings_hub_apply_saves_pending_hoyolab_credentials`.
   - Gap:
     - release/parity gate 기준으로는 실제 게임 실행, OBS, screenshot, notification, sidebar overlay, clipboard paste Windows runtime smoke가 필요하다. current-device scope에서는 `docs/v2-gui-windows-logic-review.md` 코드 비교로 대체한다.

5. **Requirement 5 — build-time v1/v2 중 하나를 단일 main GUI로 선택**
   - Evidence:
     - `src/gui/mode.py`: CLI/env/packaged `gui_mode.txt` precedence와 v1/v2 normalization.
     - `homework_helper.pyw`: resolved mode에 따라 `MainWindow` 또는 `V2MainWindow`를 선택.
     - `build.py`: v1/v2 main GUI 선택, `gui_mode.txt` staging, prototype shell은 별도 preview path로 분리.
     - `installer.iss`: v1/v2는 `homework_helper.exe`, prototype mode만 `homework_helper_gui.exe`를 user-facing shortcut/run target으로 사용.
     - `tests/test_dashboard_static_build.py::test_build_gui_mode_controls_v1_v2_single_pyqt_entrypoint_and_shell_steps`.
     - `tests/test_dashboard_static_build.py::test_build_can_stage_v1_v2_runtime_gui_mode_marker`.
     - `tests/test_v2_gui_mode.py::test_homework_helper_selects_v2_window_from_resolved_mode`.
   - Gap:
     - release/parity gate 기준으로는 Windows Inno installer shortcut/run smoke가 필요하다. current-device scope에서는 `docs/v2-gui-windows-logic-review.md` 코드 비교로 대체한다.

## Required gates and evidence

| Gate or artifact | Evidence | Completion impact |
| --- | --- | --- |
| Migration inventory | `docs/migration-feature-inventory.md` updated for v1/v2/prototype packaging, v2 settings hub, build mode, HoYoLab in-place save | Required trace present |
| Feature matrix | `tests/migration/feature_matrix.json` tracks automated tests and manual smoke per Feature ID | Required trace present |
| Smoke checklist | `docs/migration-smoke-checklist.md` tracks Windows-only runtime items | Required trace present, execution still pending |
| Windows logic review | `docs/v2-gui-windows-logic-review.md` maps Windows-only smoke to code comparison evidence for current-device acceptance | Current-device substitute trace present |
| Full verification | `python tools/verify_project.py --full` | Automated gate passes locally and includes migration audit plus v2 completion audit trace |
| Real AppData fixture | `tools/verify_project.py --full` runs real AppData ZIP clone checks when `HomeworkHelper.zip` is present | Automated clone gate passes locally |

## Current stop condition

Do **not** call `update_goal(status="complete")` as a declaration of migration parity until the Windows-only checklist in `docs/migration-smoke-checklist.md` is executed and passes, or until an equivalent Windows runtime verification artifact is added to this repository. In the current-device user scope, Windows-only manual smoke is an explicitly excluded known gap, not an automated implementation blocker.
