import logging
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QWidget, QFormLayout, QLineEdit, QTextEdit, QPushButton, QCheckBox,
    QMessageBox, QSplitter, QGroupBox, QSpinBox, QTimeEdit
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QBrush

from src.utils.game_preset_manager import GamePresetManager

logger = logging.getLogger(__name__)

class PresetEditorDialog(QDialog):
    """게임 프리셋 관리/편집 다이얼로그"""
    
    def __init__(self, parent: Optional[QWidget] = None, initial_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle("게임 프리셋 관리")
        self.resize(800, 600)
        
        self.manager = GamePresetManager()
        self.initial_data = initial_data
        
        # UI 초기화
        self._init_ui()
        
        # 데이터 로드
        self._load_presets()
        
        # 초기 데이터가 있으면 신규 추가 모드로 시작
        if self.initial_data:
            self._start_add_new_mode(self.initial_data)

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
        
        # 호요버스 관련
        self.is_hoyoverse_check = QCheckBox("호요버스 게임 (스태미나 추적 지원)")
        self.mvp_enabled_check = QCheckBox("MVP 기능 사용 (YOLO 학습 필요)")
        
        self.form_layout.addRow("ID (고유 식별자):", self.id_edit)
        self.form_layout.addRow("표시 이름:", self.name_edit)
        self.form_layout.addRow("실행 파일 (EXE):", self.exe_patterns_edit)
        self.form_layout.addRow("서버 초기화 시각:", self.reset_time_edit)
        self.form_layout.addRow("기본 실행 주기 (시간):", self.cycle_hours_spin)
        self.form_layout.addRow("", self.is_hoyoverse_check)
        self.form_layout.addRow("", self.mvp_enabled_check)
        
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

    def _load_presets(self):
        """프리셋 목록 로드 및 표시"""
        self.preset_list_widget.clear()
        
        presets = self.manager.get_all_presets()
        # 정렬: 시스템 프리셋 -> 사용자 프리셋
        # 하지만 명확한 구분이 없으므로, user_presets에 있는 ID인지 확인해야 함
        
        # 현재 로드된 사용자 프리셋 ID 목록 가져오기 (manager 내부 변수 접근 대신 간접 확인)
        # GamePresetManager에 public 메서드가 없으므로, 파일 내용을 직접 확인하거나
        # load 시에 user_preset인지 표시를 해뒀어야 함.
        # 여기서는 편의상 manager의 _user_presets 속성을 참조하거나 (비공개지만),
        # 구조를 변경하지 않고 'is_system' 같은 플래그를 추론해야 함.
        # 사용자 프리셋 파일에 있는 ID 목록을 다시 로드해서 확인
        user_ids = set()
        user_presets_data = self.manager._user_presets # 백도어 접근 (실용적 해결)
        for p in user_presets_data:
            user_ids.add(p.get("id"))
            
        presets.sort(key=lambda p: p.get("display_name", ""))
        
        for preset in presets:
            pid = preset.get("id")
            name = preset.get("display_name", "Unknown")
            
            is_user = pid in user_ids
            
            display_text = f"{name}"
            if is_user:
                display_text += " (사용자)"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, preset)
            item.setData(Qt.ItemDataRole.UserRole + 1, is_user) # 사용자 정의 여부
            
            if is_user:
                item.setForeground(QBrush(QColor("#0066cc"))) # 파란색
            
            self.preset_list_widget.addItem(item)

    def _start_add_new_mode(self, prefill_data: Optional[Dict[str, Any]] = None):
        """신규 추가 모드로 전환"""
        self.preset_list_widget.clearSelection()
        self.form_group.setTitle("새 프리셋 추가")
        self.id_edit.setEnabled(True)
        self.id_edit.clear()
        self.name_edit.clear()
        self.exe_patterns_edit.clear()
        
        # 시간/주기 초기화 (SpecialValueText가 나오도록)
        self.reset_time_edit.setTime(self.reset_time_edit.minimumTime())
        self.cycle_hours_spin.setValue(0)
        
        self.is_hoyoverse_check.setChecked(False)
        self.mvp_enabled_check.setChecked(False)
        
        self.save_btn.setText("신규 프리셋 등록")
        self.save_btn.setEnabled(True)
        self.delete_btn.setEnabled(False)
        
        # 자동 완성 데이터 적용
        if prefill_data:
            if "name" in prefill_data:
                self.name_edit.setText(prefill_data["name"])
                # 이름 기반 ID 추천
                import re
                safe_id = re.sub(r'[^a-zA-Z0-9]', '_', prefill_data["name"]).lower().strip('_')
                self.id_edit.setText(safe_id)
                
            if "exe_path" in prefill_data and prefill_data["exe_path"]:
                import os
                exe_name = os.path.basename(prefill_data["exe_path"])
                self.exe_patterns_edit.setPlainText(exe_name)
                
            if "reset_time" in prefill_data and prefill_data["reset_time"]:
                from PyQt6.QtCore import QTime
                try:
                    t = QTime.fromString(prefill_data["reset_time"], "HH:mm")
                    if t.isValid():
                        self.reset_time_edit.setTime(t)
                except:
                    pass
                    
            if "cycle_hours" in prefill_data and prefill_data["cycle_hours"]:
                self.cycle_hours_spin.setValue(int(prefill_data["cycle_hours"]))

    def _on_preset_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        """목록에서 프리셋 선택 시 상세 정보 표시"""
        if not current:
            return
            
        preset = current.data(Qt.ItemDataRole.UserRole)
        is_user = current.data(Qt.ItemDataRole.UserRole + 1)
        
        self.form_group.setTitle(f"프리셋 정보 ({'사용자' if is_user else '시스템'})")
        
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
        
        self.is_hoyoverse_check.setChecked(preset.get("is_hoyoverse", False))
        self.mvp_enabled_check.setChecked(preset.get("mvp_enabled", False))
        
        # 편집 가능 여부 설정
        if is_user:
            self.id_edit.setEnabled(False) # ID는 수정 불가
            self.name_edit.setEnabled(True)
            self.exe_patterns_edit.setEnabled(True)
            self.reset_time_edit.setEnabled(True)
            self.cycle_hours_spin.setEnabled(True)
            self.is_hoyoverse_check.setEnabled(True)
            self.mvp_enabled_check.setEnabled(True)
            
            self.save_btn.setText("변경사항 저장")
            self.save_btn.setEnabled(True)
            self.delete_btn.setEnabled(True)
        else:
            # 시스템 프리셋은 읽기 전용
            self.id_edit.setEnabled(False)
            self.name_edit.setEnabled(False)
            self.exe_patterns_edit.setEnabled(False)
            self.reset_time_edit.setEnabled(False)
            self.cycle_hours_spin.setEnabled(False)
            self.is_hoyoverse_check.setEnabled(False)
            self.mvp_enabled_check.setEnabled(False)
            
            self.save_btn.setText("시스템 프리셋은 수정 불가")
            self.save_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)

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
        
        # 데이터 구성
        new_data = {
            "id": preset_id,
            "display_name": display_name,
            "exe_patterns": exe_patterns,
            "is_hoyoverse": self.is_hoyoverse_check.isChecked(),
            "mvp_enabled": self.mvp_enabled_check.isChecked()
        }
        
        # 시간/주기 (설정 안 함이 아니면 추가)
        if self.reset_time_edit.time() != self.reset_time_edit.minimumTime():
            new_data["server_reset_time"] = self.reset_time_edit.time().toString("HH:mm")
            
        if self.cycle_hours_spin.value() > 0:
            new_data["default_cycle_hours"] = self.cycle_hours_spin.value()
            
        # 신규인지 수정인지 확인
        # 현재 선택된 아이템이 있고 ID가 같으면 수정 (하지만 ID 수정은 막았으므로...)
        # 사용자 목록에 ID가 있는지 확인하여 Update 또는 Add 호출
        
        user_ids = {p.get("id") for p in self.manager._user_presets}
        
        success = False
        if preset_id in user_ids:
            # 수정
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
        is_user = current_item.data(Qt.ItemDataRole.UserRole + 1)
        
        if not is_user:
            return
            
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
