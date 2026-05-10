# Migration Feature Inventory

This inventory tracks user-visible parity work while the packaged Tauri/React GUI remains a preview and the installed default GUI remains the PyQt `homework_helper.exe` shell.

| ID | Area | Existing contract / data boundary | Current status | Verification |
| --- | --- | --- | --- | --- |
| GUI-TABLE-001 | Main PyQt game table | Reads managed processes through `ApiClient` / data models; no direct DB writes from UI. | Headers and row numbers are hidden; display order is fixed to game-name ascending; table/window size is derived from cell widgets, font metrics, layout size hints, and screen clamp; oversized content falls back to table overflow scrolling instead of expanding off-screen. | `tests/test_gui_layout.py::test_main_table_hides_headers_and_uses_fixed_name_sort`; `tests/test_gui_layout.py::test_main_table_enables_overflow_scrollbar_instead_of_oversizing_screen`; `tests/test_gui_layout.py::test_restore_window_state_does_not_leave_fixed_size`; real AppData clone screenshot using `HomeworkHelper.zip`. |
| SIDEBAR-001 | PyQt sidebar drawer | Reads sidebar settings through `GlobalSettings`; existing auto-hide remains owned by sidebar controller/widget. | Drawer frame is borderless; while sidebar is enabled for an active game the click handle is always visible and not transparent-for-input, so this diagnostic path bypasses hover show/hide gating and verifies click-to-`slide_in()` separately. | `tests/test_gui_layout.py::test_edge_trigger_starts_with_always_visible_borderless_click_handle`; `tests/test_gui_layout.py::test_edge_trigger_click_invokes_callback_without_hiding_handle`; `tests/test_gui_layout.py::test_sidebar_controller_edge_trigger_callback_slides_sidebar_in`; `tests/test_gui_layout.py::test_sidebar_frame_css_remains_borderless`. |
| REALDATA-001 | Real AppData fixture | `HomeworkHelper.zip` is read-only and extracted only into temporary clones/artifacts. | GUI sizing was checked against cloned `homework_helper_data/app_data.db` rows from the ZIP fixture. | Local ignored screenshot artifact under `artifacts/gui-screenshots/`; ZIP remains ignored/untracked. |

## Sidebar legacy comparison

- Legacy baseline (`cd87638^`) used a transparent right-edge strip and `QCursor.pos()` polling; entering the hover zone called `_fire_trigger()` directly without a visible handle or click step.
- Current diagnostic path shows the handle from `EdgeTriggerWindow.start()`, removes cursor-position hover gating from the active path, and tests the click callback through `SidebarController._on_edge_triggered()` to `SidebarWidget.slide_in()`.
