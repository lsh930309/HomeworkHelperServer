import logging
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QWidget, QFormLayout, QLineEdit, QTextEdit, QPushButton, QCheckBox,
    QMessageBox, QSplitter, QGroupBox, QSpinBox, QTimeEdit, QComboBox
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QBrush

from src.utils.game_preset_manager import GamePresetManager

logger = logging.getLogger(__name__)

class PresetEditorDialog(QDialog):
    """게임 프리셋 관리/편집 다이얼로그"""
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("게임 프리셋 관리")
        self.resize(800, 650)
        
        self.manager = GamePresetManager()
        
        # UI 초기화
        self._init_ui()
        
        # 프리셋 로드
        self._load_presets()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # --- 좌측: 프리셋 목록 ---
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        left_layout.addWidget(QLabel("프리셋 목록"))
        self.preset_list_widget = QListWidget()
        self.preset_list_widget.currentItemChanged.connect(self._on_preset_selected)
        left_layout.addWidget(self.preset_list_widget)
        
        # 목록 하단 버튼
        list_btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("신규 추가")
        self.add_btn.clicked.connect(lambda: self._start_add_new_mode())
        list_btn_layout.addWidget(self.add_btn)
        
        self.delete_btn = QPushButton("삭제")
        self.delete_btn.clicked.connect(self._delete_current_preset)
        self.delete_btn.setEnabled(False)
        list_btn_layout.addWidget(self.delete_btn)
        
        left_layout.addLayout(list_btn_layout)
        
        splitter.addWidget(left_widget)
        
        # --- 우측: 상세 편집 ---
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 0, 0, 0)
        
        # 편집 폼
        self.form_group = QGroupBox("프리셋 상세 정보")
        self.form_layout = QFormLayout(self.form_group)
        
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("영문 소문자, 숫자, 언더스코어(_)만 사용")
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("사용자에게 표시될 이름")
        
        self.exe_patterns_edit = QTextEdit()
        self.exe_patterns_edit.setPlaceholderText("실행 파일 이름 (줄바꿈으로 구분, 예: game.exe)")
        self.exe_patterns_edit.setMaximumHeight(100)
        
        self.reset_time_edit = QTimeEdit()
        self.reset_time_edit.setDisplayFormat("HH:mm")
        self.reset_time_edit.setSpecialValueText("설정 안 함") # 값이 없음을 표현하기 위해
        self.reset_time_edit.setTime(self.reset_time_edit.minimumTime()) # 기본값을 00:00으로 설정하지만 SpecialValueText가 보이게 함

        self.cycle_hours_spin = QSpinBox()
        self.cycle_hours_spin.setRange(0, 168)
        self.cycle_hours_spin.setSpecialValueText("설정 안 함")
        
        # [NEW] Mandatory Times
        self.mandatory_times_edit = QLineEdit()
        self.mandatory_times_edit.setPlaceholderText("예: 12:00, 18:00 (쉼표로 구분)")
        
        # [NEW] Launch Type
        self.launch_type_combo = QComboBox()
        self.launch_type_combo.addItem("기본 (바로가기 우선)", "shortcut")
        self.launch_type_combo.addItem("프로세스 직접 실행 우선", "direct")
        
        # 호요버스 관련
        self.is_hoyoverse_check = QCheckBox("호요버스 게임 (스태미나 추적 지원)")
        self.is_hoyoverse_check.toggled.connect(self._update_hoyolab_combo_state)
        
        # [NEW] HoYoLab Game ID
        self.hoyolab_game_combo = QComboBox()
        self.hoyolab_game_combo.addItem("선택 안 함", None)
        self.hoyolab_game_combo.addItem("붕괴: 스타레일", "honkai_starrail")
        self.hoyolab_game_combo.addItem("젠레스 존 제로", "zenless_zone_zero")

        self.form_layout.addRow("ID (고유 식별자):", self.id_edit)
        self.form_layout.addRow("표시 이름:", self.name_edit)
        self.form_layout.addRow("실행 파일 (EXE):", self.exe_patterns_edit)
        self.form_layout.addRow("서버 초기화 시각:", self.reset_time_edit)
        self.form_layout.addRow("기본 실행 주기 (시간):", self.cycle_hours_spin)
        self.form_layout.addRow("특정 접속 시각:", self.mandatory_times_edit)
        self.form_layout.addRow("실행 방식 선호:", self.launch_type_combo)
        self.form_layout.addRow("", self.is_hoyoverse_check)
        self.form_layout.addRow("HoYoLab 게임 ID:", self.hoyolab_game_combo)

        right_layout.addWidget(self.form_group)
        
        # 저장 버튼
        save_btn_layout = QHBoxLayout()
        save_btn_layout.addStretch()
        
        self.save_btn = QPushButton("프리셋 등록/저장")
        self.save_btn.setMinimumHeight(40)
        self.save_btn.setStyleSheet("font-weight: bold; background-color: #e1f5fe;")
        self.save_btn.clicked.connect(self._save_preset)
        save_btn_layout.addWidget(self.save_btn)
        
        right_layout.addLayout(save_btn_layout)
        right_layout.addStretch()
        
        splitter.addWidget(right_widget)
        
        # 초기 분할 비율 설정
        splitter.setSizes([250, 550])
        
        self._update_hoyolab_combo_state(False)

    def _update_hoyolab_combo_state(self, checked: bool):
        """호요버스 체크 여부에 따라 콤보박스 활성화"""
        self.hoyolab_game_combo.setEnabled(checked)

    def _load_presets(self):
        """프리셋 목록 로드 및 표시"""
        self.preset_list_widget.clear()
        
        presets = self.manager.get_all_presets()
        presets.sort(key=lambda p: p.get("display_name", ""))
        
        for preset in presets:
            name = preset.get("display_name", "Unknown")
            
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, preset)
            
            self.preset_list_widget.addItem(item)

    def _start_add_new_mode(self):
        """신규 추가 모드로 전환"""
        self.preset_list_widget.clearSelection()
        self.form_group.setTitle("새 프리셋 추가")
        self.id_edit.setEnabled(True)
        self.id_edit.clear()
        self.name_edit.clear()
        self.exe_patterns_edit.clear()
        
        # 시간/주기 초기화
        self.reset_time_edit.setTime(self.reset_time_edit.minimumTime())
        self.cycle_hours_spin.setValue(0)
        self.mandatory_times_edit.clear()
        self.launch_type_combo.setCurrentIndex(0)
        self.hoyolab_game_combo.setCurrentIndex(0)

        self.is_hoyoverse_check.setChecked(False)

        self.save_btn.setText("신규 프리셋 등록")
        self.save_btn.setEnabled(True)
        self.delete_btn.setEnabled(False)

    def _on_preset_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        """목록에서 프리셋 선택 시 상세 정보 표시"""
        if not current:
            return
            
        preset = current.data(Qt.ItemDataRole.UserRole)
        
        self.form_group.setTitle("프리셋 정보")
        
        # 데이터 바인딩
        self.id_edit.setText(preset.get("id", ""))
        self.name_edit.setText(preset.get("display_name", ""))
        self.exe_patterns_edit.setPlainText("\n".join(preset.get("exe_patterns", [])))
        
        # Reset Time
        reset_time = preset.get("server_reset_time")
        if reset_time:
            from PyQt6.QtCore import QTime
            t = QTime.fromString(reset_time, "HH:mm")
            if t.isValid():
                self.reset_time_edit.setTime(t)
            else:
                self.reset_time_edit.setTime(self.reset_time_edit.minimumTime())
        else:
            self.reset_time_edit.setTime(self.reset_time_edit.minimumTime())
            
        # Cycle Hours
        self.cycle_hours_spin.setValue(preset.get("default_cycle_hours", 0))
        
        # [NEW] Mandatory Times
        mandatory = preset.get("mandatory_times", [])
        if isinstance(mandatory, list):
            self.mandatory_times_edit.setText(", ".join(mandatory))
        else:
            self.mandatory_times_edit.clear()
            
        # [NEW] Launch Type
        launch_type = preset.get("preferred_launch_type", "shortcut")
        idx = self.launch_type_combo.findData(launch_type)
        if idx >= 0:
            self.launch_type_combo.setCurrentIndex(idx)
        else:
            self.launch_type_combo.setCurrentIndex(0)
        
        # HoYoVerse
        is_hoyo = preset.get("is_hoyoverse", False)
        self.is_hoyoverse_check.setChecked(is_hoyo)

        # [NEW] HoYoLab ID
        hoyolab_id = preset.get("hoyolab_game_id")
        if hoyolab_id:
            idx = self.hoyolab_game_combo.findData(hoyolab_id)
            if idx >= 0:
                self.hoyolab_game_combo.setCurrentIndex(idx)
            else:
                # 데이터엔 있지만 콤보에 없으면 추가 후 선택? or ignore
                self.hoyolab_game_combo.setCurrentIndex(0)
        else:
            self.hoyolab_game_combo.setCurrentIndex(0)
        
        # 모든 프리셋 편집 가능
        self.id_edit.setEnabled(False) # ID는 여전히 키값이므로 수정 불가
        self.name_edit.setEnabled(True)
        self.exe_patterns_edit.setEnabled(True)
        self.reset_time_edit.setEnabled(True)
        self.cycle_hours_spin.setEnabled(True)
        self.mandatory_times_edit.setEnabled(True)
        self.launch_type_combo.setEnabled(True)
        self.is_hoyoverse_check.setEnabled(True)
        self.hoyolab_game_combo.setEnabled(is_hoyo) # Checkbox state syncs this, but ensure consistency

        self.save_btn.setText("변경사항 저장")
        self.save_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _save_preset(self):
        """프리셋 저장/업데이트"""
        # 검증
        preset_id = self.id_edit.text().strip()
        display_name = self.name_edit.text().strip()
        exe_patterns_str = self.exe_patterns_edit.toPlainText().strip()
        
        if not preset_id:
            QMessageBox.warning(self, "입력 오류", "ID를 입력해주세요.")
            return
        if not display_name:
            QMessageBox.warning(self, "입력 오류", "표시 이름을 입력해주세요.")
            return
        if not exe_patterns_str:
            QMessageBox.warning(self, "입력 오류", "최소 하나 이상의 실행 파일 패턴을 입력해주세요.")
            return
        
        exe_patterns = [line.strip() for line in exe_patterns_str.splitlines() if line.strip()]
        
        # [NEW] Mandatory Times Parse
        mandatory_times_str = self.mandatory_times_edit.text().strip()
        mandatory_times = []
        if mandatory_times_str:
            parts = [p.strip() for p in mandatory_times_str.split(",")]
            # 간단한 포맷 검증 (HH:MM)
            import re
            time_pat = re.compile(r"^\d{1,2}:\d{2}$")
            for t in parts:
                if not time_pat.match(t):
                    QMessageBox.warning(self, "입력 오류", f"시간 형식이 올바르지 않습니다: {t}\nHH:MM 형식으로 입력해주세요.")
                    return
                # 정규화 (09:00 -> 09:00)
                mandatory_times.append(t)
        
        # 데이터 구성
        new_data = {
            "id": preset_id,
            "display_name": display_name,
            "exe_patterns": exe_patterns,
            "is_hoyoverse": self.is_hoyoverse_check.isChecked(),
            "preferred_launch_type": self.launch_type_combo.currentData(),
            "mandatory_times": mandatory_times
        }
        
        # HoYoLab ID
        if self.is_hoyoverse_check.isChecked():
            hid = self.hoyolab_game_combo.currentData()
            if hid:
                new_data["hoyolab_game_id"] = hid
        
        # 시간/주기 (설정 안 함이 아니면 추가)
        if self.reset_time_edit.time() != self.reset_time_edit.minimumTime():
            new_data["server_reset_time"] = self.reset_time_edit.time().toString("HH:mm")
            
        if self.cycle_hours_spin.value() > 0:
            new_data["default_cycle_hours"] = self.cycle_hours_spin.value()
            
        # 신규인지 수정인지 확인
        existing_preset = self.manager.get_preset_by_id(preset_id)
        
        success = False
        if existing_preset:
            # 수정 (기존 ID가 존재하면 업데이트)
            # 단, 현재 선택된 아이템이 아닌 다른 아이템의 ID를 입력했을 경우 덮어쓰기 경고가 필요할 수 있음
            # 하지만 ID 수정은 막혀있으므로, 현재 선택된 아이템의 업데이트이거나
            # 신규 추가 모드에서 기존 ID를 입력한 경우임.
            if self.id_edit.isEnabled(): # 신규 추가 모드였다면
                 reply = QMessageBox.question(
                    self, 
                    "덮어쓰기 확인", 
                    f"이미 존재하는 ID '{preset_id}' 입니다. 덮어쓰시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                 if reply == QMessageBox.StandardButton.No:
                     return

            success = self.manager.update_user_preset(preset_id, new_data)
            action = "수정"
        else:
            # 신규 추가
            success = self.manager.add_user_preset(new_data)
            action = "추가"
            
        if success:
            QMessageBox.information(self, "성공", f"프리셋이 {action}되었습니다.")
            self.manager.reload()
            self._load_presets()
            
            # 방금 추가/수정한 아이템 찾아서 선택
            for i in range(self.preset_list_widget.count()):
                item = self.preset_list_widget.item(i)
                data = item.data(Qt.ItemDataRole.UserRole)
                if data.get("id") == preset_id:
                    self.preset_list_widget.setCurrentItem(item)
                    break
        else:
            QMessageBox.critical(self, "실패", f"프리셋 {action}에 실패했습니다.")

    def _delete_current_preset(self):
        """현재 선택된 프리셋 삭제"""
        current_item = self.preset_list_widget.currentItem()
        if not current_item:
            return
            
        preset = current_item.data(Qt.ItemDataRole.UserRole)
        
        reply = QMessageBox.question(
            self, 
            "삭제 확인", 
            f"정말로 프리셋 '{preset.get('display_name')}'을(를) 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.manager.remove_user_preset(preset.get("id")):
                QMessageBox.information(self, "삭제 완료", "프리셋이 삭제되었습니다.")
                self.manager.reload()
                self._load_presets()
                self._start_add_new_mode()
            else:
                QMessageBox.critical(self, "삭제 실패", "프리셋 삭제 중 오류가 발생했습니다.")
