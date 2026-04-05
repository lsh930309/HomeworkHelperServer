import os
import datetime
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QTableWidgetItem, QDialog, QVBoxLayout, QLabel, QTableWidget,
    QDialogButtonBox, QHeaderView, QWidget, QFormLayout, QPushButton,
    QLineEdit, QHBoxLayout, QFileDialog, QMessageBox, QCheckBox,
    QTimeEdit, QDoubleSpinBox, QSpinBox, QComboBox, QGroupBox, QApplication,
    QRadioButton, QButtonGroup, QScrollArea,
)
from PyQt6.QtCore import Qt, QTime
from PyQt6.QtGui import QIcon # QIcon might be needed if dialogs use icons directly

# Local imports
from src.data.data_models import ManagedProcess, GlobalSettings
from src.utils.process import get_all_running_processes_info # Used by RunningProcessSelectionDialog
from src.utils.common import copy_shortcut_file # 바로가기 파일 복사 기능

class NumericTableWidgetItem(QTableWidgetItem):
    """ QTableWidgetItem that allows numeric sorting. """
    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return super().__lt__(other)

class RunningProcessSelectionDialog(QDialog):
    """ Dialog to select a running process from a list. """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("실행 중인 프로세스 선택")
        self.selected_process_info: Optional[Dict[str, Any]] = None

        self.setMinimumSize(750, 500)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("현재 실행 중인 프로세스 목록 (컬럼 헤더 클릭 시 정렬):"))

        self.process_list_widget = QTableWidget()
        self.process_list_widget.setColumnCount(6)
        self.process_list_widget.setHorizontalHeaderLabels(["", "PID", "이름", "실행 파일 경로", "메모리(MB)", "CPU(%)"])
        self.process_list_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.process_list_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.process_list_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.process_list_widget.setSortingEnabled(True)

        header = self.process_list_widget.horizontalHeader()
        if header:  # None 체크 추가
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) # Icon
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents) # PID
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)      # Name
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)          # Path
            header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents) # Memory
            header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents) # CPU

        self.process_list_widget.setColumnWidth(0, 32) # Icon column width
        self.process_list_widget.setColumnWidth(2, 200) # Name column initial width
        layout.addWidget(self.process_list_widget)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(self.button_box)

        # Connections
        self.process_list_widget.doubleClicked.connect(self.accept)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.populate_running_processes()

    def populate_running_processes(self):
        """ Fetches and displays currently running processes in the table. """
        self.process_list_widget.setSortingEnabled(False)
        processes = get_all_running_processes_info() # External function
        self.process_list_widget.setRowCount(len(processes))

        for row, proc_info in enumerate(processes):
            q_icon = proc_info.get('q_icon')
            pid_val = proc_info.get('pid', 0)
            name_val = proc_info.get('name', 'N/A')
            exe_val = proc_info.get('exe', 'N/A')
            mem_val_mb = proc_info.get('memory_rss_mb', 0.0)
            cpu_val_percent = proc_info.get('cpu_percent', 0.0)

            icon_item = QTableWidgetItem()
            if q_icon and not q_icon.isNull(): # q_icon is QIcon from process_utils
                icon_item.setIcon(q_icon)

            pid_item = NumericTableWidgetItem(str(pid_val))
            name_item = QTableWidgetItem(name_val)
            exe_item = QTableWidgetItem(exe_val)
            mem_item = NumericTableWidgetItem(f"{mem_val_mb:.1f}")
            cpu_item = NumericTableWidgetItem(f"{cpu_val_percent:.1f}")

            name_item.setData(Qt.ItemDataRole.UserRole, proc_info)

            self.process_list_widget.setItem(row, 0, icon_item)
            self.process_list_widget.setItem(row, 1, pid_item)
            self.process_list_widget.setItem(row, 2, name_item)
            self.process_list_widget.setItem(row, 3, exe_item)
            self.process_list_widget.setItem(row, 4, mem_item)
            self.process_list_widget.setItem(row, 5, cpu_item)

        self.process_list_widget.setSortingEnabled(True)
        self.process_list_widget.sortByColumn(4, Qt.SortOrder.DescendingOrder) # Sort by Memory

    def accept(self):
        """ Overrides QDialog.accept() to store selected process info. """
        selection_model = self.process_list_widget.selectionModel()
        if selection_model:  # None 체크 추가
            selected_rows = selection_model.selectedRows()
            if selected_rows:
                selected_row_index = selected_rows[0].row()
                item_with_data = self.process_list_widget.item(selected_row_index, 2) # Name item
                if item_with_data:
                    self.selected_process_info = item_with_data.data(Qt.ItemDataRole.UserRole)
        super().accept()

    def get_selected_process_info(self) -> Optional[Dict[str, Any]]:
        """ Returns the dictionary of the selected process. """
        return self.selected_process_info

class ProcessDialog(QDialog):
    """ Dialog for adding a new process or editing an existing one. """
    def __init__(self, parent: Optional[QWidget] = None, existing_process: Optional[ManagedProcess] = None):
        super().__init__(parent)
        self.existing_process = existing_process

        if self.existing_process:
            self.setWindowTitle("프로세스 편집")
        else:
            self.setWindowTitle("새 프로세스 추가")

        self.setMinimumWidth(450)
        self.form_layout = QFormLayout(self)  # 변수명 변경

        self.select_running_button = QPushButton("실행 중인 프로세스에서 자동 완성...")
        self.name_edit = QLineEdit()
        self.monitoring_path_edit = QLineEdit()
        self.monitoring_path_button = QPushButton("찾아보기...")
        self.launch_path_edit = QLineEdit()
        self.launch_path_button = QPushButton("찾아보기...")
        self.server_reset_time_edit = QLineEdit()
        self.user_cycle_hours_edit = QLineEdit()
        self.mandatory_times_edit = QLineEdit()
        self.is_mandatory_time_enabled_checkbox = QCheckBox("특정 접속 시간 알림 활성화")

        self.form_layout.addRow(self.select_running_button)
        
        # --- 프리셋 선택 섹션 추가 ---
        self._setup_preset_section()
        
        self.form_layout.addRow("이름 (비워두면 자동 생성):", self.name_edit)

        monitor_path_layout = QHBoxLayout()
        monitor_path_layout.addWidget(self.monitoring_path_edit)
        monitor_path_layout.addWidget(self.monitoring_path_button)
        self.form_layout.addRow("모니터링 경로 (필수):", monitor_path_layout)

        launch_path_layout = QHBoxLayout()
        launch_path_layout.addWidget(self.launch_path_edit)
        launch_path_layout.addWidget(self.launch_path_button)
        self.form_layout.addRow("실행 경로 (비워두면 모니터링 경로 사용):", launch_path_layout)

        self.form_layout.addRow("서버 초기화 시각 (HH:MM):", self.server_reset_time_edit)
        self.form_layout.addRow("사용자 실행 주기 (시간):", self.user_cycle_hours_edit)
        self.form_layout.addRow("특정 접속 시각 (HH:MM, 쉼표로 구분):", self.mandatory_times_edit)
        self.form_layout.addRow(self.is_mandatory_time_enabled_checkbox)

        # 실행 방식 선택 섹션
        self._setup_launch_type_section()

        # 스태미나 추적 섹션 (호요버스 게임 전용)
        self._setup_stamina_section()

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.form_layout.addRow(self.button_box)

        self.select_running_button.clicked.connect(self.open_running_process_selector)
        self.monitoring_path_button.clicked.connect(
            lambda: self.browse_file(self.monitoring_path_edit)
        )
        self.launch_path_button.clicked.connect(
            lambda: self.browse_file(self.launch_path_edit)
        )
        self.button_box.accepted.connect(self.accept_data)
        self.button_box.rejected.connect(self.reject)
        
        # 실행 방식 선택 콤보박스 활성화 상태 업데이트 (경로 변경 시)
        self.monitoring_path_edit.textChanged.connect(self._update_launch_type_enabled)
        self.launch_path_edit.textChanged.connect(self._update_launch_type_enabled)

        if self.existing_process:
            self.populate_fields_from_existing_process()

    def _setup_preset_section(self):
        """프리셋 선택 및 저장 섹션 설정"""
        from src.utils.game_preset_manager import GamePresetManager
        
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("프리셋:"))
        
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("선택 안 함", None)
        
        # 프리셋 목록 로드
        try:
            self.preset_manager = GamePresetManager()
            presets = self.preset_manager.get_all_presets()
            
            # 정렬: 시스템 프리셋 먼저, 그 다음 이름순
            # (여기서는 간단히 이름순으로 정렬하되, 원본 순서도 고려할 수 있음)
            presets.sort(key=lambda p: p.get("display_name", ""))
            
            for preset in presets:
                display_name = preset.get("display_name", "Unknown")
                preset_id = preset.get("id")
                # 사용자 정의 프리셋 표시
                if not preset_id:
                     continue
                self.preset_combo.addItem(display_name, preset)


        except Exception as e:
            logger.warning(f"프리셋 로드 실패: {e}")

        preset_layout.addWidget(self.preset_combo, 1) # 늘어나도록 설정
        
        # 적용 버튼
        self.apply_preset_button = QPushButton("적용")
        self.apply_preset_button.setToolTip("선택한 프리셋의 설정을 현재 입력창에 적용합니다.")
        self.apply_preset_button.clicked.connect(self._on_apply_preset_clicked)
        preset_layout.addWidget(self.apply_preset_button)
        
        # 현재 설정을 프리셋으로 저장 버튼 (신규 추가 모드로 프리셋 에디터 열기)
        self.save_as_preset_button = QPushButton("현재 설정을 프리셋으로 저장")
        self.save_as_preset_button.setToolTip("현재 입력된 설정값으로 새 프리셋을 등록합니다.")
        self.save_as_preset_button.clicked.connect(self._on_save_as_preset_clicked)
        preset_layout.addWidget(self.save_as_preset_button)
        
        # 프리셋 관리 버튼 (목록 보기/편집)
        self.manage_presets_button = QPushButton("프리셋 관리...")
        self.manage_presets_button.setToolTip("기존 프리셋 목록을 확인하고 편집합니다.")
        self.manage_presets_button.clicked.connect(self._open_preset_manager)
        preset_layout.addWidget(self.manage_presets_button)
        
        self.form_layout.addRow(preset_layout)

    def _open_preset_manager(self):
        """프리셋 관리자 열기"""
        from src.gui.preset_editor_dialog import PresetEditorDialog
        dialog = PresetEditorDialog(self)

        dialog.presets_changed.connect(self._refresh_parent_main_window_presets)
        dialog.exec()
        self._refresh_preset_combo()

    def _on_save_as_preset_clicked(self):
        """현재 입력값을 템플릿으로 넘겨 프리셋 에디터에서 바로 저장합니다."""
        from src.gui.preset_editor_dialog import PresetEditorDialog

        exe_path = self.monitoring_path_edit.text().strip()
        if not exe_path:
            QMessageBox.warning(self, "입력 필요", "모니터링 경로를 먼저 입력해야 프리셋으로 저장할 수 있습니다.")
            return

        exe_name = os.path.basename(exe_path)
        display_name = self.name_edit.text().strip() or os.path.splitext(exe_name)[0] or "새 프리셋"
        reset_time = self.server_reset_time_edit.text().strip() or None
        cycle_hours = self.user_cycle_hours_edit.text().strip()
        cycle_hours_int = int(cycle_hours) if cycle_hours.isdigit() else None
        mandatory_times = [
            t.strip()
            for t in self.mandatory_times_edit.text().strip().split(",")
            if t.strip()
        ]
        is_hoyoverse = (
            hasattr(self, "stamina_tracking_checkbox")
            and self.stamina_tracking_checkbox.isChecked()
        )
        hoyolab_game_id = None
        if is_hoyoverse and hasattr(self, "hoyolab_game_combo"):
            hoyolab_game_id = self.hoyolab_game_combo.currentData()

        template = {
            "display_name": display_name,
            # Steam/Epic 같은 클라이언트 설치 게임은 .lnk/.url 바로가기를
            # 모니터링 대상으로 두는 경우가 많으므로 basename을 그대로 보존한다.
            "exe_patterns": [exe_name] if exe_name else [],
            "server_reset_time": reset_time,
            "default_cycle_hours": cycle_hours_int,
            "mandatory_times": mandatory_times,
            "preferred_launch_type": self.launch_type_combo.currentData() if hasattr(self, "launch_type_combo") else "shortcut",
            "is_hoyoverse": is_hoyoverse,
            "hoyolab_game_id": hoyolab_game_id,
        }

        dialog = PresetEditorDialog(self)
        dialog.presets_changed.connect(self._refresh_parent_main_window_presets)
        dialog.prepare_new_preset(template)
        dialog.exec()

        self._refresh_preset_combo()
        saved_preset_id = dialog.get_last_saved_preset_id()
        if saved_preset_id:
            for i in range(self.preset_combo.count()):
                preset_data = self.preset_combo.itemData(i)
                if preset_data and preset_data.get("id") == saved_preset_id:
                    self.preset_combo.setCurrentIndex(i)
                    break

    def _refresh_parent_main_window_presets(self) -> None:
        """상위 MainWindow가 있으면 프리셋 관련 UI를 다시 그립니다."""
        main_window = self.parent()
        while main_window and not hasattr(main_window, 'refresh_presets_and_ui'):
            main_window = main_window.parent()
        if main_window and hasattr(main_window, 'refresh_presets_and_ui'):
            main_window.refresh_presets_and_ui()

    def _on_apply_preset_clicked(self):
        """선택한 프리셋 적용"""
        preset = self.preset_combo.currentData()
        if not preset:
            return
            
        reply = QMessageBox.question(
            self,
            "프리셋 적용",
            f"프리셋 '{preset.get('display_name')}' 설정을 적용하시겠습니까?\n"
            "현재 입력된 내용이 덮어씌워질 수 있습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._apply_preset_data(preset)
            QMessageBox.information(self, "적용 완료", "프리셋 설정이 적용되었습니다.")

    def _apply_preset_data(self, preset: Dict[str, Any]):
        """프리셋 데이터를 UI 필드에 적용"""
        # 이름 적용 (비어있거나 덮어쓰기)
        if hasattr(self, 'name_edit'):
            self.name_edit.setText(preset.get("display_name", ""))
            
        # 서버 초기화 시간
        if "server_reset_time" in preset:
            self.server_reset_time_edit.setText(preset["server_reset_time"])
            
        # 사용자 주기
        if "default_cycle_hours" in preset:
            self.user_cycle_hours_edit.setText(str(preset["default_cycle_hours"]))
            
        # [NEW] Mandatory Times
        if "mandatory_times" in preset and hasattr(self, 'mandatory_times_edit'):
            m_times = preset["mandatory_times"]
            if isinstance(m_times, list):
                self.mandatory_times_edit.setText(", ".join(m_times))
            else:
                self.mandatory_times_edit.setText(str(m_times))
                
        # [NEW] Launch Type
        if "preferred_launch_type" in preset and hasattr(self, 'launch_type_combo'):
            l_type = preset["preferred_launch_type"]
            idx = self.launch_type_combo.findData(l_type)
            if idx >= 0:
                self.launch_type_combo.setCurrentIndex(idx)

        # 호요버스 게임 설정
        if preset.get("is_hoyoverse", False):
            if hasattr(self, 'stamina_tracking_checkbox'):
                self.stamina_tracking_checkbox.setChecked(True)

            # 호요랩 게임 자동 선택
            if hasattr(self, 'hoyolab_game_combo'):
                hid = preset.get("hoyolab_game_id")
                if hid:
                    index = self.hoyolab_game_combo.findData(hid)
                    if index >= 0:
                        self.hoyolab_game_combo.setCurrentIndex(index)

    # _on_save_as_preset_clicked 메서드는 위에서 재정의됨 (직접 코드 삭제 대신 위쪽 청크에서 덮어쓰거나 빈 메서드로 대체 필요하지만, 
    # multi_replace는 덮어쓰기이므로, 기존 _on_save_as_preset_clicked 메서드 전체를 이 청크로 대체하는 게 나을 수도 있음.
    # 하지만 여기서는 _apply_preset_data 뒤에 오는 _on_save_as_preset_clicked를 제거해야 함.
    # 해당 메서드는 파일 뒷부분에 있음. 
    # 차라리 별도 청크로 삭제 처리.

    def _refresh_preset_combo(self):
        """프리셋 콤보박스 목록 갱신"""
        current_data = self.preset_combo.currentData()
        
        self.preset_combo.clear()
        self.preset_combo.addItem("선택 안 함", None)
        
        self.preset_manager.reload()
        presets = self.preset_manager.get_all_presets()
        presets.sort(key=lambda p: p.get("display_name", ""))
        
        for preset in presets:
            display_name = preset.get("display_name", "Unknown")
            preset_id = preset.get("id")
            if not preset_id: continue
            self.preset_combo.addItem(display_name, preset)
            
        # 이전에 선택했던 항목 복구 시도
        if current_data:
            index = self.preset_combo.findData(current_data)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)

    def _setup_launch_type_section(self):
        """실행 방식 선택 섹션 설정"""
        launch_type_layout = QHBoxLayout()
        launch_type_layout.addWidget(QLabel("실행 방식:"))
        
        self.launch_type_combo = QComboBox()
        self.launch_type_combo.addItem("바로가기 선호 (기본)", "shortcut")
        self.launch_type_combo.addItem("프로세스 선호", "direct")
        self.launch_type_combo.addItem("런처 선호", "launcher")
        self.launch_type_combo.setToolTip(
            "모니터링 경로와 실행 경로가 다를 때 기본 실행 대상을 선택합니다.\n"
            "• 바로가기 선호: 실행 경로(바로가기)를 우선 사용, 없으면 모니터링 경로 사용\n"
            "• 프로세스 선호: 모니터링 경로(실행 파일)를 우선 사용, 없으면 실행 경로 사용\n"
            "• 런처 선호: 프리셋의 launcher_patterns 로 찾은 런처를 우선 사용하고, 없으면 기존 경로로 폴백"
        )
        launch_type_layout.addWidget(self.launch_type_combo)
        launch_type_layout.addStretch()
        
        self.form_layout.addRow(launch_type_layout)
        
        # 초기 상태 설정 (비활성화 - 경로가 같으면)
        # 시그널 연결은 모든 위젯 초기화 후에 한 번만 하도록 __init__ 마지막에서 처리
        self._update_launch_type_enabled()

    def _ensure_launch_type_option(self, launch_type: Optional[str]) -> str:
        """저장된 실행 방식이 콤보에 없으면 추가해 round-trip을 보장합니다."""
        normalized = (launch_type or "shortcut").strip().lower()
        if normalized == "auto":
            normalized = "shortcut"
        if not normalized:
            normalized = "shortcut"

        if self.launch_type_combo.findData(normalized) >= 0:
            return normalized

        label_map = {
            "shortcut": "바로가기 선호 (기본)",
            "direct": "프로세스 선호",
            "launcher": "런처 선호",
        }
        display_text = label_map.get(normalized, f"기존 값 유지 ({normalized})")
        self.launch_type_combo.addItem(display_text, normalized)
        return normalized

    def _update_launch_type_enabled(self, _=None):
        """모니터링 경로와 실행 경로가 다를 때만 실행 방식 선택 활성화"""
        # 콤보박스가 아직 생성되지 않은 경우 무시
        if not hasattr(self, 'launch_type_combo'):
            return
            
        monitoring = self.monitoring_path_edit.text().strip()
        launch = self.launch_path_edit.text().strip()
        
        # 실행 경로가 비어있거나 모니터링 경로와 같으면 비활성화
        is_different = bool(launch and monitoring != launch)
        self.launch_type_combo.setEnabled(is_different)
        

    def _setup_stamina_section(self):
        """스태미나 추적 섹션 설정 (호요버스 게임 전용)"""
        self.stamina_group_box = QGroupBox("스태미나 자동 추적 (호요버스 게임)")
        stamina_layout = QVBoxLayout()

        # 스태미나 자동 추적 활성화 체크박스
        self.stamina_tracking_checkbox = QCheckBox("스태미나 자동 추적 활성화")
        self.stamina_tracking_checkbox.setToolTip(
            "게임 종료 시 HoYoLab API를 통해 스태미나(개척력/배터리)를 자동으로 조회합니다."
        )
        self.stamina_tracking_checkbox.toggled.connect(self._on_stamina_tracking_toggled)
        stamina_layout.addWidget(self.stamina_tracking_checkbox)

        # 호요버스 게임 선택 콤보박스
        hoyolab_game_layout = QHBoxLayout()
        hoyolab_game_layout.addWidget(QLabel("추적할 게임:"))
        self.hoyolab_game_combo = QComboBox()
        self.hoyolab_game_combo.addItem("(없음)", None)
        self.hoyolab_game_combo.addItem("붕괴: 스타레일", "honkai_starrail")
        self.hoyolab_game_combo.addItem("젠레스 존 제로", "zenless_zone_zero")
        self.hoyolab_game_combo.setToolTip("스태미나를 추적할 호요버스 게임을 선택하세요.")
        hoyolab_game_layout.addWidget(self.hoyolab_game_combo)
        hoyolab_game_layout.addStretch()
        stamina_layout.addLayout(hoyolab_game_layout)

        # 스태미나 조회 테스트 버튼
        self.stamina_test_button = QPushButton("스태미나 조회 테스트")
        self.stamina_test_button.setToolTip("HoYoLab API 연결을 테스트하고 현재 스태미나를 조회합니다.")
        self.stamina_test_button.clicked.connect(self._test_stamina_connection)
        stamina_layout.addWidget(self.stamina_test_button)

        self.stamina_group_box.setLayout(stamina_layout)
        self.form_layout.addRow(self.stamina_group_box)

        # 초기 상태: 체크박스 상태에 따라 콤보박스 활성화
        self._on_stamina_tracking_toggled(False)

    def _on_stamina_tracking_toggled(self, checked: bool):
        """스태미나 추적 체크박스 상태 변경 시"""
        if checked:
            # 체크박스 활성화 시 콤보박스 활성화
            self.hoyolab_game_combo.setEnabled(True)
        else:
            # 체크박스 비활성화 시 콤보박스를 '(없음)'으로 설정하고 비활성화
            self.hoyolab_game_combo.setCurrentIndex(0)  # '(없음)' 선택
            self.hoyolab_game_combo.setEnabled(False)

    def _test_stamina_connection(self):
        """스태미나 조회 테스트"""
        # 호요랩 게임 콤보박스에서 선택된 게임 사용
        game_id = self.hoyolab_game_combo.currentData()
        if not game_id:
            QMessageBox.warning(self, "오류", "추적할 호요버스 게임을 선택해주세요.")
            return

        try:
            from src.services.hoyolab import get_hoyolab_service

            service = get_hoyolab_service()

            # 라이브러리 확인
            if not service.is_available():
                QMessageBox.warning(
                    self,
                    "라이브러리 없음",
                    "HoYoLab API 연동을 위한 genshin.py 라이브러리가 설치되지 않았습니다.\n\n"
                    "설치 방법: pip install genshin"
                )
                return

            # 인증 정보 확인
            if not service.is_configured():
                reply = QMessageBox.question(
                    self,
                    "인증 정보 없음",
                    "HoYoLab 인증 정보가 설정되지 않았습니다.\n"
                    "지금 설정하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )
                if reply == QMessageBox.StandardButton.Yes:
                    from src.gui.dialogs import HoYoLabSettingsDialog
                    dialog = HoYoLabSettingsDialog(self)
                    dialog.exec()
                    # 설정 후 다시 확인
                    if not service.is_configured():
                        return
                else:
                    return

            # 스태미나 조회
            game_names = {
                "honkai_starrail": "붕괴: 스타레일",
                "zenless_zone_zero": "젠레스 존 제로"
            }
            game_name = game_names.get(game_id, game_id)

            # 커서를 대기 커서로 변경
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()  # UI 업데이트

            try:
                stamina_info = service.get_stamina(game_id)

                if stamina_info:
                    full_time_str = ""
                    if stamina_info.full_time:
                        full_time_str = f"\n완전 회복 예상: {stamina_info.full_time.strftime('%Y-%m-%d %H:%M:%S')}"

                    stamina_name = "개척력" if game_id == "honkai_starrail" else "배터리"

                    # 편집 모드인 경우 프로세스에 스태미나 정보 즉시 저장
                    save_result = ""
                    if self.existing_process:
                        try:
                            # 로컬 객체 업데이트
                            self.existing_process.stamina_current = stamina_info.current
                            self.existing_process.stamina_max = stamina_info.max
                            self.existing_process.stamina_updated_at = stamina_info.updated_at.timestamp()

                            # API를 통해 전체 프로세스 업데이트
                            parent_window = self.parent()
                            if parent_window and hasattr(parent_window, 'data_manager'):
                                result = parent_window.data_manager.update_process(self.existing_process)
                                if result:
                                    save_result = "\n\n💾 스태미나 정보가 저장되었습니다."
                                    # GUI 새로고침
                                    if hasattr(parent_window, 'populate_process_list'):
                                        parent_window.populate_process_list()
                                else:
                                    save_result = "\n\n⚠️ 스태미나 정보 저장 실패"
                            else:
                                save_result = "\n\n💾 스태미나 정보가 임시 저장되었습니다."
                        except Exception as e:
                            logger.error(f"스태미나 저장 오류: {e}", exc_info=True)
                            save_result = f"\n\n⚠️ 저장 오류: {e}"
                    else:
                        save_result = "\n\nℹ️ 프로세스 저장 시 함께 저장됩니다."

                    QMessageBox.information(
                        self,
                        "스태미나 조회 성공",
                        f"✅ {game_name} 스태미나 조회 성공!\n\n"
                        f"{stamina_name}: {stamina_info.current} / {stamina_info.max}\n"
                        f"회복까지: {stamina_info.recover_time // 60}분{full_time_str}\n"
                        f"조회 시각: {stamina_info.updated_at.strftime('%Y-%m-%d %H:%M:%S')}"
                        f"{save_result}"
                    )
                else:
                    QMessageBox.warning(
                        self,
                        "조회 실패",
                        f"❌ {game_name} 스태미나 조회에 실패했습니다.\n\n"
                        "가능한 원인:\n"
                        "• HoYoLab 쿠키가 만료되었습니다.\n"
                        "• 해당 게임을 플레이하지 않았습니다.\n"
                        "• API 서버에 문제가 있습니다.\n\n"
                        "HoYoLab 설정에서 쿠키를 다시 설정해보세요."
                    )
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "오류",
                    f"스태미나 조회 중 오류가 발생했습니다:\n{str(e)}"
                )
            finally:
                # 커서를 원래대로 복원
                QApplication.restoreOverrideCursor()

        except ImportError:
            QMessageBox.warning(
                self,
                "모듈 없음",
                "HoYoLab 서비스 모듈을 찾을 수 없습니다."
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "오류",
                f"스태미나 테스트 중 오류가 발생했습니다:\n{str(e)}"
            )

    def populate_fields_from_existing_process(self):
        if not self.existing_process:
            return
        self.name_edit.setText(self.existing_process.name)
        self.monitoring_path_edit.setText(self.existing_process.monitoring_path)
        self.launch_path_edit.setText(self.existing_process.launch_path)
        if self.existing_process.server_reset_time_str:
            self.server_reset_time_edit.setText(self.existing_process.server_reset_time_str)
        if self.existing_process.user_cycle_hours is not None:
            self.user_cycle_hours_edit.setText(str(self.existing_process.user_cycle_hours))
        if self.existing_process.mandatory_times_str:
            self.mandatory_times_edit.setText(",".join(self.existing_process.mandatory_times_str))
        self.is_mandatory_time_enabled_checkbox.setChecked(self.existing_process.is_mandatory_time_enabled)

        # 실행 방식 선택 로드
        if hasattr(self.existing_process, 'preferred_launch_type'):
            launch_type = self._ensure_launch_type_option(
                self.existing_process.preferred_launch_type
            )
            for i in range(self.launch_type_combo.count()):
                if self.launch_type_combo.itemData(i) == launch_type:
                    self.launch_type_combo.setCurrentIndex(i)
                    break
            # 활성화 상태 업데이트
            self._update_launch_type_enabled()

        # 프리셋 자동 선택
        if hasattr(self.existing_process, 'user_preset_id') and self.existing_process.user_preset_id:
            for i in range(self.preset_combo.count()):
                preset_data = self.preset_combo.itemData(i)
                if preset_data and preset_data.get("id") == self.existing_process.user_preset_id:
                    self.preset_combo.setCurrentIndex(i)
                    logger.debug(f"프리셋 자동 선택: {self.existing_process.user_preset_id}")
                    break

        # 호요랩 게임 선택 로드 (스태미나 추적보다 먼저 설정)
        if hasattr(self.existing_process, 'hoyolab_game_id') and self.existing_process.hoyolab_game_id:
            for i in range(self.hoyolab_game_combo.count()):
                if self.hoyolab_game_combo.itemData(i) == self.existing_process.hoyolab_game_id:
                    self.hoyolab_game_combo.setCurrentIndex(i)
                    break
        else:
            # hoyolab_game_id가 None이면 '(없음)' 선택
            self.hoyolab_game_combo.setCurrentIndex(0)

        # 스태미나 추적 필드 로드 (콤보박스 설정 후 체크박스 설정)
        if hasattr(self.existing_process, 'stamina_tracking_enabled'):
            self.stamina_tracking_checkbox.setChecked(self.existing_process.stamina_tracking_enabled)

        # 체크박스 상태에 따라 콤보박스 활성화/비활성화
        self._on_stamina_tracking_toggled(self.stamina_tracking_checkbox.isChecked())

    def open_running_process_selector(self):
        dialog = RunningProcessSelectionDialog(self) # Uses dialog defined above
        if dialog.exec():
            selected_info = dialog.get_selected_process_info()
            if selected_info:
                exe_path = selected_info.get('exe', '')
                proc_name_from_psutil = selected_info.get('name', '')
                base_name = os.path.basename(exe_path if exe_path else proc_name_from_psutil)
                default_name = os.path.splitext(base_name)[0]
                if not default_name and proc_name_from_psutil:
                    default_name = os.path.splitext(proc_name_from_psutil)[0]
                self.name_edit.setText(default_name or '')
                self.monitoring_path_edit.setText(exe_path)
                self.launch_path_edit.setText(exe_path)

                # 프리셋 자동 감지 및 적용 (GamePresetManager 사용)
                try:
                    from src.utils.game_preset_manager import GamePresetManager
                    manager = GamePresetManager()
                    preset = manager.detect_game_from_exe(exe_path)
                    
                    if preset:
                        self._apply_preset_data(preset)
                        logger.debug(f"프리셋 '{preset.get('id')}' 자동 감지 및 적용 완료")
                except Exception as e:
                    logger.warning(f"프리셋 자동 적용 실패: {e}")

    def browse_file(self, path_edit_widget: QLineEdit):
        """ 파일 대화상자를 열어 파일을 선택하고, 선택된 파일의 경로를 입력 위젯에 설정합니다. """
        # 파일 필터 수정: .url 파일을 포함하도록 변경
        filters = [
            "모든 지원 파일 (*.exe *.bat *.cmd *.lnk *.url)", # 기본 필터
            "실행 파일 (*.exe *.bat *.cmd)",
            "바로 가기 (*.lnk *.url)", # .url을 바로 가기에 명시적으로 포함
            "모든 파일 (*)"
        ]
        filter_string = ";;".join(filters)
        
        # QFileDialog.getOpenFileName은 선택된 파일의 경로를 반환합니다.
        # .lnk나 .url 파일의 경우, 해당 파일 자체의 경로가 반환됩니다 (대상의 경로가 아님).
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "파일 선택", 
            "",  # 시작 디렉토리 (비워두면 마지막 사용 디렉토리 또는 기본값)
            filter_string
        )
        if file_path:
            # 바로가기 파일인 경우 자동으로 복사
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext in ['.lnk', '.url']:
                # 편집 모드일 때 기존 프로세스 ID 사용 (중복 방지)
                process_id = self.existing_process.id if self.existing_process else None
                copied_path = copy_shortcut_file(file_path, process_id)
                if copied_path:
                    # 복사된 파일 경로를 입력 필드에 설정
                    path_edit_widget.setText(copied_path)
                    QMessageBox.information(
                        self, 
                        "바로가기 파일 복사 완료", 
                        f"바로가기 파일이 자동으로 복사되었습니다.\n원본: {os.path.basename(file_path)}\n복사본: {os.path.basename(copied_path)}"
                    )
                else:
                    # 복사 실패 시 원본 경로 사용
                    path_edit_widget.setText(file_path)
                    QMessageBox.warning(
                        self, 
                        "바로가기 파일 복사 실패", 
                        f"바로가기 파일 복사에 실패했습니다. 원본 경로를 사용합니다.\n{file_path}"
                    )
            else:
                # 일반 실행 파일인 경우 원본 경로 그대로 사용
                path_edit_widget.setText(file_path)

    def validate_time_format(self, time_str: str) -> bool:
        if not time_str:
            return True
        try:
            datetime.datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    def accept_data(self):
        if not self.monitoring_path_edit.text().strip():
            QMessageBox.warning(self, "입력 오류", "모니터링 경로를 입력해야 합니다.")
            return

        reset_time_str = self.server_reset_time_edit.text().strip()
        if reset_time_str and not self.validate_time_format(reset_time_str):
            QMessageBox.warning(self, "입력 오류", f"서버 초기화 시각 형식이 잘못되었습니다 (HH:MM): {reset_time_str}")
            return

        cycle_hours_str = self.user_cycle_hours_edit.text().strip()
        if cycle_hours_str:
            try:
                int(cycle_hours_str)
            except ValueError:
                QMessageBox.warning(self, "입력 오류", f"사용자 실행 주기는 숫자로 입력해야 합니다: {cycle_hours_str}")
                return

        mandatory_times_list_str = self.mandatory_times_edit.text().strip()
        if mandatory_times_list_str:
            times = [t.strip() for t in mandatory_times_list_str.split(",")]
            for t_str in times:
                if t_str and not self.validate_time_format(t_str):
                    QMessageBox.warning(self, "입력 오류", f"특정 접속 시각 형식이 잘못되었습니다 (HH:MM): {t_str}")
                    return
        self.accept()

    def get_data(self) -> Optional[Dict[str, Any]]:
        name = self.name_edit.text().strip()
        monitoring_path = self.monitoring_path_edit.text().strip()
        if not monitoring_path:
            return None

        launch_path = self.launch_path_edit.text().strip()
        final_launch_path = launch_path if launch_path else monitoring_path
        server_reset_time_str = self.server_reset_time_edit.text().strip()
        server_reset_time = server_reset_time_str if server_reset_time_str else None
        user_cycle_hours_str = self.user_cycle_hours_edit.text().strip()
        user_cycle_hours: Optional[int] = None
        if user_cycle_hours_str:
            try:
                user_cycle_hours = int(user_cycle_hours_str)
            except ValueError:
                user_cycle_hours = None

        mandatory_times_raw = self.mandatory_times_edit.text().strip()
        mandatory_times_list: List[str] = []
        if mandatory_times_raw:
            mandatory_times_list = [t.strip() for t in mandatory_times_raw.split(",") if t.strip()]

        is_mandatory_enabled = self.is_mandatory_time_enabled_checkbox.isChecked()

        # 실행 방식 선택
        preferred_launch_type = self._ensure_launch_type_option(
            self.launch_type_combo.currentData()
        )

        # 프리셋 ID 추출
        preset_data = self.preset_combo.currentData()
        user_preset_id = preset_data.get("id") if preset_data else None

        # 스태미나 추적 필드
        hoyolab_game_id = self.hoyolab_game_combo.currentData()
        # hoyolab_game_id가 None이면 스태미나 추적도 자동으로 비활성화
        stamina_tracking_enabled = self.stamina_tracking_checkbox.isChecked() and hoyolab_game_id is not None

        # 스태미나 추적이 비활성화되면 hoyolab_game_id도 null로 설정
        if not stamina_tracking_enabled:
            hoyolab_game_id = None

        return {
            "name": name,
            "monitoring_path": monitoring_path,
            "launch_path": final_launch_path,
            "server_reset_time_str": server_reset_time,
            "user_cycle_hours": user_cycle_hours,
            "mandatory_times_str": mandatory_times_list if mandatory_times_list else None,
            "is_mandatory_time_enabled": is_mandatory_enabled,
            "preferred_launch_type": preferred_launch_type,
            "user_preset_id": user_preset_id,
            "stamina_tracking_enabled": stamina_tracking_enabled,
            "hoyolab_game_id": hoyolab_game_id,
        }

class GlobalSettingsDialog(QDialog):
    """ Dialog for configuring global application settings. """
    def __init__(self, current_settings: GlobalSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("전역 설정")
        self.current_settings = current_settings
        self.resize(560, 620)

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            max_w = max(320, available.width() - 80)
            max_h = max(240, available.height() - 80)
            min_w = min(520, max_w)
            min_h = min(460, max_h)
            self.setMinimumSize(min_w, min_h)
            self.setMaximumSize(max_w, max_h)
        else:
            self.setMinimumSize(520, 460)

        outer_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)
        scroll.setWidget(content)

        # === 화면 배율 설정 (OS DPI 무시) ===
        self.scale_combo = QComboBox()
        self.scale_combo.addItem("100%", 100)
        self.scale_combo.addItem("125%", 125)
        self.scale_combo.addItem("150%", 150)
        self.scale_combo.addItem("175%", 175)
        self.scale_combo.addItem("200%", 200)
        
        scale_info_label = QLabel("※ 변경 시 앱 재시작 필요")
        scale_info_label.setStyleSheet("color: #888888; font-size: 9pt;")
        
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(self.scale_combo)
        scale_layout.addWidget(scale_info_label)
        scale_layout.addStretch()
        # =====================================

        self.sleep_start_edit = QTimeEdit()
        self.sleep_start_edit.setDisplayFormat("HH:mm")
        self.sleep_end_edit = QTimeEdit()
        self.sleep_end_edit.setDisplayFormat("HH:mm")
        self.sleep_correction_hours_spinbox = QDoubleSpinBox()
        self.sleep_correction_hours_spinbox.setRange(0.0, 5.0)
        self.sleep_correction_hours_spinbox.setSingleStep(0.5)
        self.sleep_correction_hours_spinbox.setSuffix(" 시간 전")
        self.cycle_advance_hours_spinbox = QDoubleSpinBox()
        self.cycle_advance_hours_spinbox.setRange(0.0, 12.0)
        self.cycle_advance_hours_spinbox.setSingleStep(0.25)
        self.cycle_advance_hours_spinbox.setSuffix(" 시간 전")
        self.run_on_startup_checkbox = QCheckBox("Windows 시작 시 자동 실행")
        self.run_as_admin_checkbox = QCheckBox("관리자 권한으로 실행 (UAC 프롬프트 없이)")

        # 테마 선택 (라디오 버튼)
        self.theme_system_rb = QRadioButton("시스템")
        self.theme_light_rb = QRadioButton("라이트")
        self.theme_dark_rb = QRadioButton("다크")
        self._theme_btn_group = QButtonGroup(self)
        self._theme_btn_group.addButton(self.theme_system_rb, 0)
        self._theme_btn_group.addButton(self.theme_light_rb, 1)
        self._theme_btn_group.addButton(self.theme_dark_rb, 2)
        self.theme_system_rb.setChecked(True)
        theme_rb_layout = QHBoxLayout()
        theme_rb_layout.addWidget(self.theme_system_rb)
        theme_rb_layout.addWidget(self.theme_light_rb)
        theme_rb_layout.addWidget(self.theme_dark_rb)
        theme_rb_layout.addStretch()

        # 게임 실행 시 창 숨기기
        self.hide_on_game_checkbox = QCheckBox("게임 실행 감지 시 창을 트레이로 자동 숨기기")
        # --- 알림 설정 체크박스들 ---
        self.notify_on_mandatory_time_checkbox = QCheckBox("고정 접속 시간 알림")
        self.notify_on_cycle_deadline_checkbox = QCheckBox("사용자 주기 만료 임박 알림")
        self.notify_on_sleep_correction_checkbox = QCheckBox("수면 보정(잠들기 전 미리) 알림")
        self.notify_on_daily_reset_checkbox = QCheckBox("일일 과제 마감 임박 알림")
        # 스태미나 알림 설정
        self.stamina_notify_checkbox = QCheckBox("스태미나 가득 찰 알림 (호요버스 게임)")
        self.stamina_threshold_spinbox = QSpinBox()
        self.stamina_threshold_spinbox.setRange(1, 100)
        self.stamina_threshold_spinbox.setSuffix(" 개 전")
        self.stamina_threshold_spinbox.setToolTip("스태미나가 (최대 - 이 값) 이상일 때 알림")

        appearance_group = QGroupBox("표시 및 실행")
        appearance_form = QFormLayout(appearance_group)
        appearance_form.addRow("화면 배율:", scale_layout)
        appearance_form.addRow("테마:", theme_rb_layout)
        appearance_form.addRow(self.run_on_startup_checkbox)
        appearance_form.addRow(self.run_as_admin_checkbox)
        appearance_form.addRow(self.hide_on_game_checkbox)
        content_layout.addWidget(appearance_group)

        schedule_group = QGroupBox("알림 기준 시각")
        schedule_form = QFormLayout(schedule_group)
        schedule_form.addRow("수면 시작 시각:", self.sleep_start_edit)
        schedule_form.addRow("수면 종료 시각:", self.sleep_end_edit)
        schedule_form.addRow("수면 보정 알림 (수면 시작 기준):", self.sleep_correction_hours_spinbox)
        schedule_form.addRow("일반 주기 만료 알림 (마감 기준):", self.cycle_advance_hours_spinbox)
        content_layout.addWidget(schedule_group)

        notify_group = QGroupBox("알림 유형")
        notify_layout = QVBoxLayout(notify_group)
        notify_layout.addWidget(self.notify_on_mandatory_time_checkbox)
        notify_layout.addWidget(self.notify_on_cycle_deadline_checkbox)
        notify_layout.addWidget(self.notify_on_sleep_correction_checkbox)
        notify_layout.addWidget(self.notify_on_daily_reset_checkbox)
        content_layout.addWidget(notify_group)

        stamina_group = QGroupBox("호요버스 스태미나 알림")
        stamina_form = QFormLayout(stamina_group)
        stamina_form.addRow(self.stamina_notify_checkbox)
        stamina_form.addRow("알림 시점:", self.stamina_threshold_spinbox)
        content_layout.addWidget(stamina_group)
        content_layout.addStretch(1)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        outer_layout.addWidget(self.button_box)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.populate_settings()
        
        # 배율 초기값 로드 (ini 파일에서)
        self._load_scale_setting()

    def _load_scale_setting(self):
        """ini 파일에서 배율 설정 로드"""
        try:
            import configparser
            if os.name == 'nt':
                app_data = os.getenv('APPDATA', os.path.expanduser('~'))
            else:
                app_data = os.path.expanduser('~/.config')
            
            config_path = os.path.join(app_data, 'HomeworkHelper', 'display_settings.ini')
            
            if os.path.exists(config_path):
                config = configparser.ConfigParser()
                config.read(config_path, encoding='utf-8')
                scale_percent = config.getint('Display', 'scale_percent', fallback=100)
            else:
                scale_percent = 100
            
            # 콤보박스에서 해당 값 선택
            for i in range(self.scale_combo.count()):
                if self.scale_combo.itemData(i) == scale_percent:
                    self.scale_combo.setCurrentIndex(i)
                    break
        except Exception as e:
            logger.warning(f"배율 설정 로드 실패: {e}")
    
    def _save_scale_setting(self, scale_percent: int):
        """ini 파일에 배율 설정 저장"""
        try:
            import configparser
            if os.name == 'nt':
                app_data = os.getenv('APPDATA', os.path.expanduser('~'))
            else:
                app_data = os.path.expanduser('~/.config')
            
            config_dir = os.path.join(app_data, 'HomeworkHelper')
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, 'display_settings.ini')
            
            config = configparser.ConfigParser()
            config['Display'] = {'scale_percent': str(scale_percent)}
            
            with open(config_path, 'w', encoding='utf-8') as f:
                config.write(f)

            logger.debug(f"배율 설정 저장: {scale_percent}%")
            return True
        except Exception as e:
            logger.warning(f"배율 설정 저장 실패: {e}")
            return False
    
    def accept(self):
        """설정 저장 시 배율 변경 확인 및 재시작 안내"""
        new_scale = self.scale_combo.currentData()
        
        # 기존 배율과 비교
        try:
            import configparser
            if os.name == 'nt':
                app_data = os.getenv('APPDATA', os.path.expanduser('~'))
            else:
                app_data = os.path.expanduser('~/.config')
            
            config_path = os.path.join(app_data, 'HomeworkHelper', 'display_settings.ini')
            old_scale = 100
            if os.path.exists(config_path):
                config = configparser.ConfigParser()
                config.read(config_path, encoding='utf-8')
                old_scale = config.getint('Display', 'scale_percent', fallback=100)
            
            # 배율이 변경된 경우
            if new_scale != old_scale:
                self._save_scale_setting(new_scale)
                QMessageBox.information(
                    self,
                    "재시작 필요",
                    f"화면 배율이 {old_scale}% → {new_scale}%로 변경되었습니다.\n\n"
                    "변경 사항을 적용하려면 앱을 재시작해주세요."
                )
        except Exception as e:
            logger.warning(f"배율 변경 확인 실패: {e}")
            self._save_scale_setting(new_scale)
        
        super().accept()

    def populate_settings(self):
        self.sleep_start_edit.setTime(QTime.fromString(self.current_settings.sleep_start_time_str, "HH:mm"))
        self.sleep_end_edit.setTime(QTime.fromString(self.current_settings.sleep_end_time_str, "HH:mm"))
        self.sleep_correction_hours_spinbox.setValue(self.current_settings.sleep_correction_advance_notify_hours)
        self.cycle_advance_hours_spinbox.setValue(self.current_settings.cycle_deadline_advance_notify_hours)
        self.run_on_startup_checkbox.setChecked(self.current_settings.run_on_startup)
        self.run_as_admin_checkbox.setChecked(self.current_settings.run_as_admin)
        # 테마
        theme = getattr(self.current_settings, 'theme', 'system')
        if theme == 'light':
            self.theme_light_rb.setChecked(True)
        elif theme == 'dark':
            self.theme_dark_rb.setChecked(True)
        else:
            self.theme_system_rb.setChecked(True)
        # 게임 실행 시 창 숨기기
        self.hide_on_game_checkbox.setChecked(getattr(self.current_settings, 'hide_on_game', True))
        # 알림 설정
        self.notify_on_mandatory_time_checkbox.setChecked(self.current_settings.notify_on_mandatory_time)
        self.notify_on_cycle_deadline_checkbox.setChecked(self.current_settings.notify_on_cycle_deadline)
        self.notify_on_sleep_correction_checkbox.setChecked(self.current_settings.notify_on_sleep_correction)
        self.notify_on_daily_reset_checkbox.setChecked(self.current_settings.notify_on_daily_reset)
        # 스태미나 설정
        self.stamina_notify_checkbox.setChecked(self.current_settings.stamina_notify_enabled)
        self.stamina_threshold_spinbox.setValue(self.current_settings.stamina_notify_threshold)

    def get_updated_settings(self) -> GlobalSettings:
        return GlobalSettings(
            sleep_start_time_str=self.sleep_start_edit.time().toString("HH:mm"),
            sleep_end_time_str=self.sleep_end_edit.time().toString("HH:mm"),
            sleep_correction_advance_notify_hours=self.sleep_correction_hours_spinbox.value(),
            cycle_deadline_advance_notify_hours=self.cycle_advance_hours_spinbox.value(),
            run_on_startup=self.run_on_startup_checkbox.isChecked(),
            always_on_top=self.current_settings.always_on_top,  # 메뉴바 체크박스로 관리
            run_as_admin=self.run_as_admin_checkbox.isChecked(),
            notify_on_mandatory_time=self.notify_on_mandatory_time_checkbox.isChecked(),
            notify_on_cycle_deadline=self.notify_on_cycle_deadline_checkbox.isChecked(),
            notify_on_sleep_correction=self.notify_on_sleep_correction_checkbox.isChecked(),
            notify_on_daily_reset=self.notify_on_daily_reset_checkbox.isChecked(),
            stamina_notify_enabled=self.stamina_notify_checkbox.isChecked(),
            stamina_notify_threshold=self.stamina_threshold_spinbox.value(),
            theme='light' if self.theme_light_rb.isChecked() else 'dark' if self.theme_dark_rb.isChecked() else 'system',
            hide_on_game=self.hide_on_game_checkbox.isChecked(),
        )
        
class WebShortcutDialog(QDialog):
    """ 웹 바로 가기 버튼 추가 또는 편집을 위한 다이얼로그 """
    def __init__(self, parent: Optional[QWidget] = None, shortcut_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        
        self.is_edit_mode = shortcut_data is not None
        self.setWindowTitle("웹 바로 가기 편집" if self.is_edit_mode else "새 웹 바로 가기 추가")
        self.setMinimumWidth(350)

        self.form_layout = QFormLayout(self)  # 변수명 변경

        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("예: https://www.google.com")
        
        # 새로고침 시각 입력 필드 (HH:MM, 선택 사항)
        self.refresh_time_edit = QLineEdit()
        self.refresh_time_edit.setPlaceholderText("HH:MM (예: 09:00), 비워두면 기능 미적용")
        # 선택적으로 QTimeEdit 사용 가능:
        # self.refresh_time_edit = QTimeEdit()
        # self.refresh_time_edit.setDisplayFormat("HH:mm")
        # self.refresh_time_edit.setSpecialValueText("미설정") # QTimeEdit은 None 표현이 어려울 수 있음

        self.form_layout.addRow("버튼 이름 (필수):", self.name_edit)
        self.form_layout.addRow("웹 URL (필수):", self.url_edit)
        self.form_layout.addRow("매일 초기화 시각 (선택):", self.refresh_time_edit) # 레이블 변경

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.form_layout.addRow(self.button_box)

        self.button_box.accepted.connect(self.validate_and_accept)
        self.button_box.rejected.connect(self.reject)

        if self.is_edit_mode and shortcut_data:
            self.name_edit.setText(shortcut_data.get("name", ""))
            self.url_edit.setText(shortcut_data.get("url", ""))
            # refresh_time_str 필드에서 값 로드
            refresh_time_value = shortcut_data.get("refresh_time_str")
            if refresh_time_value:
                self.refresh_time_edit.setText(refresh_time_value)
            # last_reset_timestamp는 이 다이얼로그에서 직접 수정하지 않음

    def _is_valid_hhmm(self, time_str: str) -> bool:
        """ HH:MM 형식인지 검사합니다. """
        if not time_str: # 비어있는 경우 유효 (선택 사항이므로)
            return True
        try:
            datetime.datetime.strptime(time_str, "%H:%M")
            return True
        except ValueError:
            return False

    def validate_and_accept(self):
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        refresh_time_str = self.refresh_time_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "입력 오류", "버튼 이름을 입력해야 합니다.")
            self.name_edit.setFocus(); return
        
        if not url:
            QMessageBox.warning(self, "입력 오류", "웹 URL을 입력해야 합니다.")
            self.url_edit.setFocus(); return
        
        if not (url.startswith("http://") or url.startswith("https://") or "://" in url):
            reply = QMessageBox.warning(self, "URL 형식 경고",
                                        f"입력하신 URL '{url}'이 일반적인 웹 주소 형식이 아닐 수 있습니다.\n"
                                        "그래도 이 URL을 사용하시겠습니까?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                        QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                self.url_edit.setFocus(); return
        
        if refresh_time_str and not self._is_valid_hhmm(refresh_time_str):
            QMessageBox.warning(self, "입력 오류", "새로고침 시각 형식이 잘못되었습니다 (HH:MM 형식 또는 빈 값).")
            self.refresh_time_edit.setFocus(); return
            
        self.accept()

    def get_data(self) -> Optional[Dict[str, Any]]:
        if self.result() == QDialog.DialogCode.Accepted:
            refresh_time_str = self.refresh_time_edit.text().strip()
            return {
                "name": self.name_edit.text().strip(),
                "url": self.url_edit.text().strip(),
                # 비어있으면 None으로 저장, 아니면 HH:MM 문자열 저장
                "refresh_time_str": refresh_time_str if refresh_time_str else None,
                # last_reset_timestamp는 여기서 설정하지 않음 (기존 값 유지 또는 로직에서 초기화)
            }
        return None


class HoYoLabSettingsDialog(QDialog):
    """HoYoLab 인증 정보 설정 다이얼로그
    
    브라우저 쿠키 자동 추출 또는 수동 입력을 통해 HoYoLab 인증 정보를 설정합니다.
    """
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("HoYoLab 설정")
        self.setMinimumWidth(450)
        
        layout = QVBoxLayout(self)
        
        # 안내 문구
        info_label = QLabel(
            "HoYoLab 게임 스태미나(개척력/배터리) 조회를 위해\n"
            "HoYoLab 쿠키 정보가 필요합니다."
        )

        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        

        # 자동 추출 버튼
        auto_group = QGroupBox("자동 추출")
        auto_layout = QVBoxLayout()
        
        extract_btn_layout = QHBoxLayout()
        self.extract_chrome_btn = QPushButton("크롬에서 추출")
        self.extract_edge_btn = QPushButton("엣지에서 추출")
        self.extract_firefox_btn = QPushButton("파이어폭스에서 추출")
        
        extract_btn_layout.addWidget(self.extract_chrome_btn)
        extract_btn_layout.addWidget(self.extract_edge_btn)
        extract_btn_layout.addWidget(self.extract_firefox_btn)
        auto_layout.addLayout(extract_btn_layout)
        
        # HoYoLab 로그인 버튼
        login_btn_layout = QHBoxLayout()
        self.open_hoyolab_btn = QPushButton("호요랩 로그인 열기")
        self.show_guide_btn = QPushButton("📖 수동 추출 가이드")
        login_btn_layout.addWidget(self.open_hoyolab_btn)
        login_btn_layout.addWidget(self.show_guide_btn)
        auto_layout.addLayout(login_btn_layout)
        
        self.extract_status_label = QLabel("")
        auto_layout.addWidget(self.extract_status_label)
        
        auto_group.setLayout(auto_layout)
        layout.addWidget(auto_group)
        
        # 수동 입력
        manual_group = QGroupBox("수동 입력 (고급)")
        manual_layout = QFormLayout()
        
        self.ltuid_edit = QLineEdit()
        self.ltuid_edit.setPlaceholderText("숫자로 된 사용자 ID")
        self.ltoken_edit = QLineEdit()
        self.ltoken_edit.setPlaceholderText("ltoken_v2 쿠키 값")
        self.ltmid_edit = QLineEdit()
        self.ltmid_edit.setPlaceholderText("ltmid_v2 쿠키 값")
        
        manual_layout.addRow("LTUID:", self.ltuid_edit)
        manual_layout.addRow("LTOKEN_V2:", self.ltoken_edit)
        manual_layout.addRow("LTMID_V2:", self.ltmid_edit)
        
        manual_group.setLayout(manual_layout)
        layout.addWidget(manual_group)
        
        # 상태 표시
        self.status_label = QLabel()
        self._update_status()
        layout.addWidget(self.status_label)
        
        # 버튼박스
        button_layout = QHBoxLayout()
        self.clear_btn = QPushButton("인증 정보 삭제")
        self.clear_btn.setStyleSheet("color: #ff6666;")
        button_layout.addWidget(self.clear_btn)
        button_layout.addStretch()
        
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_layout.addWidget(self.button_box)
        layout.addLayout(button_layout)
        
        # 시그널 연결
        self.extract_chrome_btn.clicked.connect(lambda: self._extract_cookies("chrome"))
        self.extract_edge_btn.clicked.connect(lambda: self._extract_cookies("edge"))
        self.extract_firefox_btn.clicked.connect(lambda: self._extract_cookies("firefox"))
        self.open_hoyolab_btn.clicked.connect(self._open_hoyolab)
        self.show_guide_btn.clicked.connect(self._show_manual_guide)
        self.clear_btn.clicked.connect(self._clear_credentials)
        self.button_box.accepted.connect(self._save_and_accept)
        self.button_box.rejected.connect(self.reject)
        
        # 기존 설정 로드
        self._load_existing_credentials()
    
    def _update_status(self):
        """현재 인증 상태 업데이트"""
        try:
            from src.utils.hoyolab_config import HoYoLabConfig
            config = HoYoLabConfig()
            if config.is_configured():
                self.status_label.setText("✅ HoYoLab 인증 정보가 설정되어 있습니다.")
                self.status_label.setStyleSheet("color: #44cc44;")
            else:
                self.status_label.setText("❌ HoYoLab 인증 정보가 없습니다.")
                self.status_label.setStyleSheet("color: #ff6666;")
        except Exception as e:
            self.status_label.setText(f"⚠️ 상태 확인 실패: {e}")
            self.status_label.setStyleSheet("color: #ffcc00;")
    
    def _load_existing_credentials(self):
        """기존 저장된 인증 정보 로드"""
        try:
            from src.utils.hoyolab_config import HoYoLabConfig
            config = HoYoLabConfig()
            creds = config.load_credentials()
            if creds:
                self.ltuid_edit.setText(str(creds.get("ltuid", "")))
                # 보안상 토큰은 마스킹
                if creds.get("ltoken_v2"):
                    self.ltoken_edit.setText("••••••••")
                    self.ltoken_edit.setToolTip("저장된 토큰이 있습니다. 변경하려면 새 값을 입력하세요.")
                if creds.get("ltmid_v2"):
                    self.ltmid_edit.setText("••••••••")
                    self.ltmid_edit.setToolTip("저장된 토큰이 있습니다. 변경하려면 새 값을 입력하세요.")
        except Exception:
            pass
    
    def _extract_cookies(self, browser: str):
        """브라우저에서 쿠키 자동 추출"""
        try:
            from src.utils.browser_cookie_extractor import BrowserCookieExtractor
            
            extractor = BrowserCookieExtractor()
            if not extractor.is_available():
                QMessageBox.warning(
                    self, "라이브러리 없음",
                    "쿠키 추출을 위한 라이브러리(pywin32, pycryptodome)가 설치되지 않았습니다."
                )
                return
            
            self.extract_status_label.setText(f"{browser}에서 쿠키 추출 중...")
            self.extract_status_label.repaint()
            
            cookies = extractor.extract_from_browser(browser)
            
            if cookies:
                self.ltuid_edit.setText(str(cookies.get("ltuid", "")))
                self.ltoken_edit.setText(cookies.get("ltoken_v2", ""))
                self.ltmid_edit.setText(cookies.get("ltmid_v2", ""))
                self.extract_status_label.setText(f"✅ {browser}에서 쿠키 추출 성공!")
                self.extract_status_label.setStyleSheet("color: #44cc44;")
            else:
                self.extract_status_label.setText(
                    f"❌ {browser}에서 HoYoLab 쿠키를 찾을 수 없습니다.\n"
                    "HoYoLab에 로그인한 후 다시 시도하세요."
                )
                self.extract_status_label.setStyleSheet("color: #ff6666;")
                
        except Exception as e:
            self.extract_status_label.setText(f"❌ 추출 실패: {e}")
            self.extract_status_label.setStyleSheet("color: #ff6666;")
    
    def _open_hoyolab(self):
        """HoYoLab 웹사이트 열기"""
        try:
            from src.utils.browser_cookie_extractor import BrowserCookieExtractor
            extractor = BrowserCookieExtractor()
            extractor.open_hoyolab_login()
            self.extract_status_label.setText("브라우저에서 HoYoLab에 로그인한 후 쿠키를 추출하세요.")
        except Exception as e:
            import webbrowser
            webbrowser.open("https://www.hoyolab.com/home")
    
    def _show_manual_guide(self):
        """수동 쿠키 추출 가이드 표시"""
        guide_text = """<h3>수동 쿠키 추출 가이드</h3>

<p>자동 추출이 실패할 경우 아래 방법으로 직접 쿠키를 추출할 수 있습니다.</p>

<h4>1. HoYoLab 로그인</h4>
<ol>
<li><a href="https://www.hoyolab.com">www.hoyolab.com</a>에 접속하여 로그인합니다.</li>
</ol>

<h4>2. 개발자 도구 열기</h4>
<ol>
<li>F12 키를 눌러 개발자 도구를 엽니다.</li>
<li><b>Application</b> 탭 (또는 Storage 탭)을 클릭합니다.</li>
<li>좌측 메뉴에서 <b>Cookies → www.hoyolab.com</b>을 선택합니다.</li>
</ol>

<h4>3. 쿠키 값 복사</h4>
<p>아래 3개의 쿠키를 찾아 값을 복사하세요:</p>
<ul>
<li><b>ltuid_v2</b> (또는 ltuid) → LTUID 필드에 입력</li>
<li><b>ltoken_v2</b> (또는 ltoken) → LTOKEN_V2 필드에 입력</li>
<li><b>ltmid_v2</b> (또는 ltmid) → LTMID_V2 필드에 입력</li>
</ul>

<h4>⚠️ 주의사항</h4>
<ul>
<li>쿠키 값은 절대 다른 사람과 공유하지 마세요!</li>
<li>쿠키가 유출되면 계정 보안이 위험해집니다.</li>
<li>이 앱은 쿠키를 로컬에만 저장하며 외부 서버로 전송하지 않습니다.</li>
</ul>
"""
        msg = QMessageBox(self)
        msg.setWindowTitle("수동 쿠키 추출 가이드")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(guide_text)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.exec()


    def _clear_credentials(self):
        """저장된 인증 정보 삭제"""
        reply = QMessageBox.question(
            self, "인증 정보 삭제",
            "저장된 HoYoLab 인증 정보를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from src.utils.hoyolab_config import HoYoLabConfig
                config = HoYoLabConfig()
                config.clear_credentials()
                
                self.ltuid_edit.clear()
                self.ltoken_edit.clear()
                self.ltmid_edit.clear()
                self._update_status()
                
                QMessageBox.information(self, "완료", "인증 정보가 삭제되었습니다.")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"삭제 실패: {e}")
    
    def _save_and_accept(self):
        """인증 정보 저장"""
        ltuid_str = self.ltuid_edit.text().strip()
        ltoken = self.ltoken_edit.text().strip()
        ltmid = self.ltmid_edit.text().strip()
        
        # 마스킹된 값인지 확인 (변경 안 한 경우)
        if ltoken == "••••••••" or ltmid == "••••••••":
            self.accept()  # 변경 없이 닫기
            return
        
        if not ltuid_str or not ltoken or not ltmid:
            QMessageBox.warning(
                self, "입력 오류",
                "모든 필드를 입력하거나 자동 추출을 사용하세요."
            )
            return
        
        try:
            ltuid = int(ltuid_str)
        except ValueError:
            QMessageBox.warning(self, "입력 오류", "LTUID는 숫자여야 합니다.")
            return
        
        try:
            from src.utils.hoyolab_config import HoYoLabConfig
            from src.services.hoyolab import reset_hoyolab_service
            
            config = HoYoLabConfig()
            if config.save_credentials(ltuid, ltoken, ltmid):
                reset_hoyolab_service()  # 서비스 인스턴스 리셋
                QMessageBox.information(self, "저장 완료", "HoYoLab 인증 정보가 저장되었습니다.")
                self.accept()
            else:
                QMessageBox.warning(self, "저장 실패", "인증 정보 저장에 실패했습니다.")
                
        except Exception as e:
            QMessageBox.warning(self, "오류", f"저장 실패: {e}")
