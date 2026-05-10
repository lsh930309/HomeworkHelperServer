# v2 GUI Windows-only Logic Review

작성일: 2026-05-10  
목적: 현재 macOS 기기에서 실행할 수 없는 Windows-only manual smoke를, 가능한 범위의 코드 비교와 자동 테스트 근거로 대체 검토한다. 이 문서는 current-device goal acceptance 근거이며, 실제 Windows release/parity smoke를 삭제하지 않는다.

## 판정 규칙

- `docs/migration-smoke-checklist.md`의 Windows-only runtime 항목은 계속 release/parity gate로 남긴다.
- 현재 기기에서는 실행 불가능하므로, v2가 v1 기능 substrate를 상속하거나 기존 Windows runtime boundary를 그대로 재사용한다는 코드 근거와 자동 테스트를 확인한다.
- v2 전용 UI가 DB/CRUD/Beholder 경계를 우회하지 않는지도 확인한다.

## Feature별 코드 비교 결론

| ID | Windows-only smoke 대체 코드 비교 | 자동 검증 근거 | current-device 판정 |
| --- | --- | --- | --- |
| APP-001 | `homework_helper.pyw`가 `resolve_gui_mode()`로 v1/v2를 고르고 v2는 `V2MainWindow(MainWindow)`를 사용한다. v2는 `FramelessWindowHint`를 제거해 OS titlebar를 유지하고 prototype preview frameless smoke와 분리된다. | `test_homework_helper_selects_v2_window_from_resolved_mode`, `test_v2_main_window_preserves_v1_feature_surface_and_os_chrome`, `test_resolve_gui_mode_falls_back_to_v1_for_invalid_values` | 코드 비교 완료 |
| APP-002 | v2가 `MainWindow`의 close/tray/single-instance 흐름을 상속하므로 tray hide/restore/quit 경로는 v1과 동일 substrate다. | `test_v2_main_window_preserves_v1_feature_surface_and_os_chrome`, migration matrix APP-002 smoke trace | 코드 비교 완료 |
| GAME-001 | v2는 v1 add/edit/delete/context-menu handlers와 DataManager boundary를 상속하고, v2 row decorator는 hidden status data를 보존한다. | `test_v2_process_rows_keep_hidden_status_data_with_visual_indicator`, `test_v2_gui_does_not_introduce_direct_db_write_paths` | 코드 비교 완료 |
| GAME-002 | v2 launch button은 v1 launch/session handlers를 그대로 사용하며 launch type tooltip만 v2 presentation으로 보강한다. | `test_v2_process_rows_keep_hidden_status_data_with_visual_indicator`, launch/API tests in feature matrix | 코드 비교 완료 |
| WEB-001 | v2는 v1 web shortcut handlers와 DataManager write boundary를 상속하고, due/done/default button state는 기존 runtime state를 QSS property로 표시한다. | web CRUD/API tests in feature matrix, migration smoke trace | 코드 비교 완료 |
| SETTINGS-001 | v2 settings hub는 기존 `GlobalSettingsDialog`, `SidebarSettingsDialog`, `HoYoLabSettingsDialog`를 tab으로 감싸고, save는 `main_gui_settings` actor를 통해 기존 boundary로 전달한다. | `test_v2_settings_hub_merges_pages_without_dropping_v1_fields`, `test_v2_settings_hub_uses_v2_theme_tokens_standalone`, `test_main_gui_settings_actor_is_labeled_as_v2_settings_hub` | 코드 비교 완료 |
| SIDEBAR-001 | v2는 sidebar settings entry를 `SettingsDialogV2` tab으로 라우팅하고 runtime sidebar controller는 v1 `MainWindow`에서 상속한다. | `test_v2_routes_legacy_settings_menu_entries_to_single_hub`, sidebar/API tests in feature matrix | 코드 비교 완료 |
| SESSION-001 | v2 launch/session lifecycle은 v1 `MainWindow`와 Beholder session guards를 상속한다. 별도 v2 DB session write path가 없다. | `test_v2_gui_does_not_introduce_direct_db_write_paths`, Beholder/session tests in feature matrix | 코드 비교 완료 |
| SCHEDULER-001 | v2는 v1 scheduler/notifier runtime을 상속한다. non-Windows toast fallback은 import/runtime smoke 대체용 안전 fallback만 제공한다. | `test_notifier_imports_and_falls_back_when_toaster_unavailable`, scheduler tests in feature matrix | 코드 비교 완료 |
| DASHBOARD-001 | v2는 v1 dashboard entrypoint와 dashboard static/API packaging을 그대로 사용한다. dashboard frontend token consistency는 별도 build/API tests가 고정한다. | dashboard build/API/token tests in feature matrix, `test_verify_project_builds_all_frontend_migration_surfaces` | 코드 비교 완료 |
| HOYOLAB-001 | v2 HoYoLab settings는 `SettingsDialogV2` tab으로 내장되고, tab Save 및 hub Apply/OK가 in-place save를 수행한다. stamina refresh/runtime actor 경계는 기존 API/Beholder tests가 유지한다. | `test_v2_hoyolab_tab_saves_credentials_in_place`, `test_v2_settings_hub_apply_saves_pending_hoyolab_credentials`, HoYoLab tests in feature matrix | 코드 비교 완료 |
| SCREENSHOT-001 | v2는 screenshot settings/runtime을 v1 `SidebarSettingsDialog`와 inherited screenshot manager path로 유지한다. | screenshot/API/CSP tests in feature matrix, `test_v2_settings_hub_merges_pages_without_dropping_v1_fields` | 코드 비교 완료 |
| RECORDING-001 | v2는 recording settings/runtime을 v1 sidebar settings page와 inherited recording manager path로 유지한다. OBS password non-exposure는 기존 API/frontend tests가 유지한다. | recording/password tests in feature matrix, `test_v2_settings_hub_merges_pages_without_dropping_v1_fields` | 코드 비교 완료 |
| BEHOLDER-001 | v2 settings actor는 `main_gui_settings`로 labeling되고, v2 전용 코드에는 direct DB/CRUD/commit 경로가 없다. | `test_main_gui_settings_actor_is_labeled_as_v2_settings_hub`, `test_v2_gui_does_not_introduce_direct_db_write_paths` | 코드 비교 완료 |
| BACKUP-001 | backup/restore runtime은 v1 app startup and Beholder restore boundary를 유지하며, v2는 별도 backup store를 만들지 않는다. | real AppData clone checks, backup/Beholder tests in feature matrix | 코드 비교 완료 |
| BUILD-001 | `build.py`는 v1/v2 single PyQt entrypoint와 prototype preview shell을 분리한다. `installer.iss`는 v1/v2에서 `homework_helper.exe`, prototype에서만 `homework_helper_gui.exe`를 user-facing target으로 쓴다. | `test_v1_build_mode_keeps_single_pyqt_entrypoint_without_prototype_shell`, `test_prototype_build_mode_keeps_preview_shell_separate_from_v2`, `test_update_installer_script_version_persists_selected_gui_mode` | 코드 비교 완료 |
| CLIPBOARD-001 | clipboard runtime/API payload는 기존 helpers/API boundary를 유지하며 v2 전용 direct clipboard write path를 추가하지 않는다. | clipboard/API tests in feature matrix, `test_v2_gui_does_not_introduce_direct_db_write_paths` | 코드 비교 완료 |

## 결론

현재 기기에서 실행 불가능한 Windows-only 항목은 위 코드 비교와 자동 테스트로 current-device goal acceptance 범위에서 대체 검토했다. 실제 Windows tray/admin/installer/OBS/screenshot/sidebar/clipboard 동작은 `docs/migration-smoke-checklist.md`에 남아 있으며, release/parity declaration 전에는 Windows 환경 또는 동등한 runtime artifact로 확인해야 한다.
