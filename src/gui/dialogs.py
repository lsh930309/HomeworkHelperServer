import os
import datetime
from typing import List, Optional, Dict, Any

from PyQt6.QtWidgets import (
    QTableWidgetItem, QDialog, QVBoxLayout, QLabel, QTableWidget,
    QDialogButtonBox, QHeaderView, QWidget, QFormLayout, QPushButton,
    QLineEdit, QHBoxLayout, QFileDialog, QMessageBox, QCheckBox,
    QTimeEdit, QDoubleSpinBox, QSpinBox, QComboBox, QGroupBox
)
from PyQt6.QtCore import Qt, QTime
from PyQt6.QtGui import QIcon # QIcon might be needed if dialogs use icons directly

# Local imports
from src.data.data_models import ManagedProcess, GlobalSettings
from src.utils.process import get_all_running_processes_info # Used by RunningProcessSelectionDialog
from src.utils.common import copy_shortcut_file # 바로가기 파일 복사 기능

# MVP 스키마 연동 (선택적 import)
try:
    from src.schema import get_available_games, detect_game_from_path, check_schema_exists
    SCHEMA_SUPPORT = True
except ImportError:
    SCHEMA_SUPPORT = False
    def get_available_games():
        return []
    def detect_game_from_path(path):
        return None
    def check_schema_exists(game_id):
        return False

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

        # MVP 스키마 연동 섹션
        self._setup_mvp_section()

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.form_layout.addRow(self.button_box)

        self.select_running_button.clicked.connect(self.open_running_process_selector)
        self.monitoring_path_button.clicked.connect(
            lambda: self.browse_file(self.monitoring_path_edit)
        )
        self.launch_path_button.clicked.connect(
            lambda: self.browse_file(self.launch_path_edit)
        )
        self.monitoring_path_edit.textChanged.connect(self._on_monitoring_path_changed)
        self.button_box.accepted.connect(self.accept_data)
        self.button_box.rejected.connect(self.reject)
        
        # 실행 방식 선택 콤보박스 활성화 상태 업데이트 (경로 변경 시)
        self.monitoring_path_edit.textChanged.connect(self._update_launch_type_enabled)
        self.launch_path_edit.textChanged.connect(self._update_launch_type_enabled)

        if self.existing_process:
            self.populate_fields_from_existing_process()

    def _setup_launch_type_section(self):
        """실행 방식 선택 섹션 설정"""
        launch_type_layout = QHBoxLayout()
        launch_type_layout.addWidget(QLabel("실행 방식:"))
        
        self.launch_type_combo = QComboBox()
        self.launch_type_combo.addItem("바로가기 선호 (기본)", "shortcut")
        self.launch_type_combo.addItem("프로세스 선호", "direct")
        self.launch_type_combo.setToolTip(
            "모니터링 경로와 실행 경로가 다를 때 기본 실행 대상을 선택합니다.\n"
            "• 바로가기 선호: 실행 경로(바로가기)를 우선 사용, 없으면 모니터링 경로 사용\n"
            "• 프로세스 선호: 모니터링 경로(실행 파일)를 우선 사용, 없으면 실행 경로 사용"
        )
        launch_type_layout.addWidget(self.launch_type_combo)
        launch_type_layout.addStretch()
        
        self.form_layout.addRow(launch_type_layout)
        
        # 초기 상태 설정 (비활성화 - 경로가 같으면)
        # 시그널 연결은 모든 위젯 초기화 후에 한 번만 하도록 __init__ 마지막에서 처리
        self._update_launch_type_enabled()

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
        
    def _setup_mvp_section(self):
        """MVP 스키마 연동 섹션 설정"""
        self.mvp_group_box = QGroupBox("게임 스키마 연동 (MVP)")
        mvp_layout = QVBoxLayout()

        # 게임 선택 드롭다운
        game_select_layout = QHBoxLayout()
        game_select_layout.addWidget(QLabel("게임:"))
        self.game_schema_combo = QComboBox()
        self.game_schema_combo.addItem("없음 (기본 모드)", None)

        # registry.json에서 게임 목록 로드
        if SCHEMA_SUPPORT:
            available_games = get_available_games()
            for game in available_games:
                game_id = game.get("game_id", "")
                game_name_kr = game.get("game_name_kr", game_id)
                self.game_schema_combo.addItem(f"{game_name_kr}", game_id)

        game_select_layout.addWidget(self.game_schema_combo)
        game_select_layout.addStretch()
        mvp_layout.addLayout(game_select_layout)

        # MVP 활성화 체크박스
        self.mvp_enabled_checkbox = QCheckBox("MVP 기능 활성화 (YOLO + OCR)")
        self.mvp_enabled_checkbox.setEnabled(False)  # Week 6 이후 활성화
        self.mvp_enabled_checkbox.setToolTip("YOLO 모델 학습 완료 후 활성화됩니다 (Week 6 이후)")
        mvp_layout.addWidget(self.mvp_enabled_checkbox)

        # 스키마 편집 버튼
        self.edit_schema_button = QPushButton("스키마 편집...")
        self.edit_schema_button.setEnabled(False)  # 게임 선택 시 활성화
        self.edit_schema_button.clicked.connect(self._open_schema_editor)
        mvp_layout.addWidget(self.edit_schema_button)

        self.mvp_group_box.setLayout(mvp_layout)
        self.form_layout.addRow(self.mvp_group_box)

        # 게임 선택 변경 시 이벤트
        self.game_schema_combo.currentIndexChanged.connect(self._on_game_schema_changed)

    def _on_game_schema_changed(self, index: int):
        """게임 선택 변경 시"""
        game_id = self.game_schema_combo.currentData()
        self.edit_schema_button.setEnabled(game_id is not None)

        if game_id and SCHEMA_SUPPORT:
            if not check_schema_exists(game_id):
                QMessageBox.warning(
                    self,
                    "경고",
                    f"게임 '{game_id}'의 스키마 파일을 찾을 수 없습니다."
                )

    def _on_monitoring_path_changed(self, path: str):
        """모니터링 경로 변경 시 자동 게임 감지"""
        if not SCHEMA_SUPPORT or not path:
            return

        # 이미 게임이 선택되어 있으면 자동 감지 안 함
        current_game_id = self.game_schema_combo.currentData()
        if current_game_id is not None:
            return

        detected_game_id = detect_game_from_path(path)
        if detected_game_id:
            # 콤보박스에서 해당 게임 찾아 선택
            for i in range(self.game_schema_combo.count()):
                if self.game_schema_combo.itemData(i) == detected_game_id:
                    self.game_schema_combo.setCurrentIndex(i)
                    break

    def _open_schema_editor(self):
        """스키마 편집 다이얼로그 열기"""
        game_id = self.game_schema_combo.currentData()
        if not game_id:
            return

        try:
            from src.gui.schema_editor_dialog import SchemaEditorDialog
            dialog = SchemaEditorDialog(game_id, self)
            dialog.exec()
        except ImportError:
            QMessageBox.information(
                self,
                "준비 중",
                "스키마 편집기가 아직 구현되지 않았습니다.\n"
                "Week 6 이후 사용 가능합니다."
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
            launch_type = self.existing_process.preferred_launch_type
            if launch_type == "auto":
                launch_type = "shortcut"
            for i in range(self.launch_type_combo.count()):
                if self.launch_type_combo.itemData(i) == launch_type:
                    self.launch_type_combo.setCurrentIndex(i)
                    break
            # 활성화 상태 업데이트
            self._update_launch_type_enabled()

        # MVP 필드 로드
        if hasattr(self.existing_process, 'game_schema_id') and self.existing_process.game_schema_id:
            for i in range(self.game_schema_combo.count()):
                if self.game_schema_combo.itemData(i) == self.existing_process.game_schema_id:
                    self.game_schema_combo.setCurrentIndex(i)
                    break

        if hasattr(self.existing_process, 'mvp_enabled'):
            self.mvp_enabled_checkbox.setChecked(self.existing_process.mvp_enabled)

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
        preferred_launch_type = self.launch_type_combo.currentData() or "shortcut"

        # MVP 스키마 연동 필드
        game_schema_id = self.game_schema_combo.currentData()
        mvp_enabled = self.mvp_enabled_checkbox.isChecked()

        return {
            "name": name,
            "monitoring_path": monitoring_path,
            "launch_path": final_launch_path,
            "server_reset_time_str": server_reset_time,
            "user_cycle_hours": user_cycle_hours,
            "mandatory_times_str": mandatory_times_list if mandatory_times_list else None,
            "is_mandatory_time_enabled": is_mandatory_enabled,
            "preferred_launch_type": preferred_launch_type,
            "game_schema_id": game_schema_id,
            "mvp_enabled": mvp_enabled,
        }

class GlobalSettingsDialog(QDialog):
    """ Dialog for configuring global application settings. """
    def __init__(self, current_settings: GlobalSettings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("전역 설정")
        self.current_settings = current_settings
        self.setMinimumWidth(400)

        self.form_layout = QFormLayout(self)  # 변수명 변경

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
        self.always_on_top_checkbox = QCheckBox("창을 항상 위에 표시") # <<< 항상 위 체크박스 추가
        self.run_as_admin_checkbox = QCheckBox("관리자 권한으로 실행 (UAC 프롬프트 없이)")
        # --- 알림 설정 체크박스들 ---
        self.notify_on_launch_success_checkbox = QCheckBox("프로세스 실행 성공 시 알림")
        self.notify_on_launch_failure_checkbox = QCheckBox("프로세스 실행 실패 시 알림")
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

        self.form_layout.addRow("수면 시작 시각:", self.sleep_start_edit)
        self.form_layout.addRow("수면 종료 시각:", self.sleep_end_edit)
        self.form_layout.addRow("수면 보정 알림 (수면 시작 기준):", self.sleep_correction_hours_spinbox)
        self.form_layout.addRow("일반 주기 만료 알림 (마감 기준):", self.cycle_advance_hours_spinbox)
        self.form_layout.addRow(self.run_on_startup_checkbox)
        self.form_layout.addRow(self.always_on_top_checkbox) # <<< 레이아웃에 추가
        self.form_layout.addRow(self.run_as_admin_checkbox)
        # 알림 설정 섹션
        self.form_layout.addRow(QLabel("알림 설정:"))
        self.form_layout.addRow(self.notify_on_launch_success_checkbox)
        self.form_layout.addRow(self.notify_on_launch_failure_checkbox)
        self.form_layout.addRow(self.notify_on_mandatory_time_checkbox)
        self.form_layout.addRow(self.notify_on_cycle_deadline_checkbox)
        self.form_layout.addRow(self.notify_on_sleep_correction_checkbox)
        self.form_layout.addRow(self.notify_on_daily_reset_checkbox)
        # 스태미나 알림 섹션
        self.form_layout.addRow(QLabel("\n스태미나 알림 (호요버스 게임):"))
        self.form_layout.addRow(self.stamina_notify_checkbox)
        self.form_layout.addRow("알림 시점:", self.stamina_threshold_spinbox)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.form_layout.addRow(self.button_box)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        self.populate_settings()

    def populate_settings(self):
        self.sleep_start_edit.setTime(QTime.fromString(self.current_settings.sleep_start_time_str, "HH:mm"))
        self.sleep_end_edit.setTime(QTime.fromString(self.current_settings.sleep_end_time_str, "HH:mm"))
        self.sleep_correction_hours_spinbox.setValue(self.current_settings.sleep_correction_advance_notify_hours)
        self.cycle_advance_hours_spinbox.setValue(self.current_settings.cycle_deadline_advance_notify_hours)
        self.run_on_startup_checkbox.setChecked(self.current_settings.run_on_startup)
        self.always_on_top_checkbox.setChecked(self.current_settings.always_on_top) # <<< 값 로드
        self.run_as_admin_checkbox.setChecked(self.current_settings.run_as_admin)
        # 알림 설정
        self.notify_on_launch_success_checkbox.setChecked(self.current_settings.notify_on_launch_success)
        self.notify_on_launch_failure_checkbox.setChecked(self.current_settings.notify_on_launch_failure)
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
            always_on_top=self.always_on_top_checkbox.isChecked(), # <<< 값 반환
            run_as_admin=self.run_as_admin_checkbox.isChecked(),
            notify_on_launch_success=self.notify_on_launch_success_checkbox.isChecked(),
            notify_on_launch_failure=self.notify_on_launch_failure_checkbox.isChecked(),
            notify_on_mandatory_time=self.notify_on_mandatory_time_checkbox.isChecked(),
            notify_on_cycle_deadline=self.notify_on_cycle_deadline_checkbox.isChecked(),
            notify_on_sleep_correction=self.notify_on_sleep_correction_checkbox.isChecked(),
            notify_on_daily_reset=self.notify_on_daily_reset_checkbox.isChecked(),
            stamina_notify_enabled=self.stamina_notify_checkbox.isChecked(),
            stamina_notify_threshold=self.stamina_threshold_spinbox.value()
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
