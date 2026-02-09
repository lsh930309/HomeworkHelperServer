import logging
from typing import Optional, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QWidget, QFormLayout, QLineEdit, QTextEdit, QPushButton, QCheckBox,
    QMessageBox, QSplitter, QGroupBox, QSpinBox, QTimeEdit, QComboBox,
    QFileDialog
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QBrush, QPixmap

from src.utils.game_preset_manager import GamePresetManager

logger = logging.getLogger(__name__)

class PresetEditorDialog(QDialog):
    """게임 프리셋 관리/편집 다이얼로그"""

    # 프리셋 변경 시그널 (저장/삭제 시 발생)
    presets_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("게임 프리셋 관리")
        self.resize(800, 650)
        
        self.manager = GamePresetManager()
        
        # 현재 편집 중인 원본 프리셋 ID (rename 시 원본 추적용)
        self._original_preset_id: Optional[str] = None
        
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

        # 스태미나/재화 아이콘
        self.icon_preview_label = QLabel()
        self.icon_preview_label.setFixedSize(48, 48)
        self.icon_preview_label.setStyleSheet("border: 1px solid #ccc; background: white;")
        self.icon_preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_path_edit = QLineEdit()
        self.icon_path_edit.setReadOnly(True)
        self.icon_path_edit.setPlaceholderText("아이콘 없음 (공란 표시)")

        self.icon_browse_btn = QPushButton("찾아보기...")
        self.icon_browse_btn.clicked.connect(self._on_browse_stamina_icon)

        self.icon_clear_btn = QPushButton("제거")
        self.icon_clear_btn.clicked.connect(self._on_clear_stamina_icon)

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
        self.launch_type_combo.addItem("런처 우선", "launcher")
        
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

        # 스태미나/재화 아이콘 섹션
        icon_label = QLabel("스태미나/재화 아이콘:")
        icon_label.setToolTip("진행률 컬럼에 표시될 아이콘 (선택사항)")
        self.form_layout.addRow(icon_label, self.icon_preview_label)

        icon_file_layout = QHBoxLayout()
        icon_file_layout.addWidget(self.icon_path_edit)
        icon_file_layout.addWidget(self.icon_browse_btn)
        icon_file_layout.addWidget(self.icon_clear_btn)
        self.form_layout.addRow("", icon_file_layout)

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
        self._original_preset_id = None  # 신규 모드에서는 원본 ID 없음
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

    def _on_preset_selected(self, current: QListWidgetItem, _previous: QListWidgetItem):
        """목록에서 프리셋 선택 시 상세 정보 표시"""
        if not current:
            return
            
        preset = current.data(Qt.ItemDataRole.UserRole)
        
        # 원본 프리셋 ID 저장 (rename 시 원본 추적용)
        self._original_preset_id = preset.get("id")
        
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

        # 스태미나 아이콘 로드
        icon_path = preset.get("icon_path")
        icon_type = preset.get("icon_type")

        if icon_path:
            self.icon_path_edit.setText(icon_path)

            # 미리보기 업데이트
            from src.utils.icon_helper import resolve_preset_icon_path
            full_path = resolve_preset_icon_path(icon_path, icon_type)
            if full_path:
                self._update_icon_preview(full_path)
        else:
            self.icon_path_edit.clear()
            self.icon_preview_label.clear()

        # 모든 프리셋 편집 가능
        self.id_edit.setEnabled(True) # ID 수정 가능 (Phase 6)
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
        
        # 신규인지 수정인지 확인 (원본 ID 기준)
        is_editing = self._original_preset_id is not None
        original_preset = self.manager.get_preset_by_id(self._original_preset_id) if is_editing else None
        
        # 입력한 ID로 기존 프리셋이 있는지 확인 (중복 ID 감지)
        target_preset = self.manager.get_preset_by_id(preset_id)

        # ID 변경 감지 (기존 프리셋 편집 중이고 ID가 변경됨)
        if original_preset and self._original_preset_id != preset_id:
            old_id = original_preset["id"]
            new_id = preset_id
            old_icon_path = original_preset.get("icon_path")
            icon_type = original_preset.get("icon_type")

            # 사용자 커스텀 아이콘이 있으면 파일명 변경
            if old_icon_path and icon_type == "user":
                from src.utils.icon_helper import ensure_custom_icons_directory
                import os

                custom_dir = ensure_custom_icons_directory()
                old_file = os.path.join(custom_dir, old_icon_path)

                if os.path.exists(old_file):
                    # 새 파일명 생성 (확장자 유지)
                    _, ext = os.path.splitext(old_icon_path)
                    new_icon_filename = f"{new_id}_stamina{ext}"
                    new_file = os.path.join(custom_dir, new_icon_filename)

                    # 파일 리네임
                    os.rename(old_file, new_file)

                    # icon_path_edit 업데이트
                    self.icon_path_edit.setText(new_icon_filename)

            # ID 변경 경고 메시지
            reply = QMessageBox.warning(
                self,
                "ID 변경 경고",
                f"프리셋 ID를 '{old_id}' → '{preset_id}'로 변경합니다.\n\n"
                "⚠️ 이 프리셋을 사용하는 기존 프로세스에서 참조가 끊어질 수 있습니다.\n"
                "관련 프로세스를 편집하여 프리셋을 다시 선택해주세요.\n\n"
                "계속하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return

        # icon_path는 파일명만 저장 (예: "honkai_starrail_stamina.png")
        icon_filename = self.icon_path_edit.text().strip()

        # 데이터 구성 (모든 필드 명시적 포함)
        new_data = {
            # 기본 필드
            "id": preset_id,
            "display_name": display_name,
            "exe_patterns": exe_patterns,
            "is_hoyoverse": self.is_hoyoverse_check.isChecked(),
            "preferred_launch_type": self.launch_type_combo.currentData(),
            "mandatory_times": mandatory_times,

            # 스태미나 아이콘
            "icon_path": icon_filename if icon_filename else None,
            "icon_type": "user" if icon_filename else None,

            # 호요버스 관련 (is_hoyoverse = False여도 null로 명시)
            "hoyolab_game_id": self.hoyolab_game_combo.currentData() if self.is_hoyoverse_check.isChecked() else None,
            "server_reset_time": self.reset_time_edit.time().toString("HH:mm") if self.reset_time_edit.time() != self.reset_time_edit.minimumTime() else None,
            "default_cycle_hours": self.cycle_hours_spin.value() if self.cycle_hours_spin.value() > 0 else None,
            "stamina_name": None,
            "stamina_max_default": None,
            "stamina_recovery_minutes": None,
            "launcher_patterns": None
        }

        # 기존 프리셋이 있으면 시스템 필드 보존 (원본 프리셋 또는 덮어쓰기 대상)
        existing_preset = original_preset or target_preset
        if existing_preset:
            for key in ["stamina_name", "stamina_max_default", "stamina_recovery_minutes", "launcher_patterns"]:
                if key in existing_preset:
                    new_data[key] = existing_preset[key]

            # 시스템 프리셋의 아이콘은 보존
            if existing_preset.get("icon_type") == "system":
                new_data["icon_path"] = existing_preset.get("icon_path")
                new_data["icon_type"] = "system"
        
        success = False
        
        # 중복 ID 감지: 입력한 ID로 기존 프리셋이 있고, (신규 추가거나 OR ID가 변경됨)
        if target_preset and (not is_editing or preset_id != self._original_preset_id):
            # 덮어쓰기 확인 필요
            reply = QMessageBox.question(
                self, 
                "덮어쓰기 확인", 
                f"이미 존재하는 ID '{preset_id}' 입니다. 덮어쓰시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
            # 덮어쓰기 진행
            success = self.manager.update_user_preset(preset_id, new_data)
            action = "덮어쓰기"
        elif is_editing:
            # 기존 프리셋 수정 (ID 변경 포함)
            if self._original_preset_id != preset_id:
                # ID가 변경된 경우: 기존 프리셋 삭제 후 새로 추가
                self.manager.delete_user_preset(self._original_preset_id)
                success = self.manager.add_user_preset(new_data)
            else:
                # ID 동일한 경우: 업데이트
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

            # 프리셋 변경 시그널 발생 (메인 윈도우 새로고침용)
            self.presets_changed.emit()
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

                # 프리셋 변경 시그널 발생 (메인 윈도우 새로고침용)
                self.presets_changed.emit()
            else:
                QMessageBox.critical(self, "삭제 실패", "프리셋 삭제 중 오류가 발생했습니다.")

    def _on_browse_stamina_icon(self):
        """스태미나 아이콘 파일 선택 다이얼로그"""
        from src.utils.icon_helper import ensure_custom_icons_directory
        import shutil
        import os

        # 프리셋 ID 확인
        preset_id = self.id_edit.text().strip()
        if not preset_id:
            QMessageBox.warning(self, "입력 오류", "프리셋 ID를 먼저 입력해주세요.")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "스태미나/재화 아이콘 선택", "",
            "Images (*.png *.jpg *.jpeg *.webp *.ico)"
        )
        if file_path:
            # 파일 확장자 추출
            _, ext = os.path.splitext(file_path)

            # 통일된 파일명: {preset_id}_stamina{ext}
            filename = f"{preset_id}_stamina{ext}"

            # 커스텀 아이콘 디렉토리에 복사
            custom_dir = ensure_custom_icons_directory()
            dest_path = os.path.join(custom_dir, filename)

            # 중복 파일명 처리
            if os.path.exists(dest_path):
                reply = QMessageBox.question(
                    self, "파일 중복",
                    f"'{filename}' 파일이 이미 존재합니다. 덮어쓰시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return

            shutil.copy(file_path, dest_path)

            # UI 업데이트 (파일명만 저장)
            self.icon_path_edit.setText(filename)
            self._update_icon_preview(dest_path)

    def _on_clear_stamina_icon(self):
        """스태미나 아이콘 제거"""
        self.icon_path_edit.clear()
        self.icon_preview_label.clear()

    def _update_icon_preview(self, icon_path: str):
        """아이콘 미리보기 업데이트"""
        import os

        if not icon_path or not os.path.exists(icon_path):
            self.icon_preview_label.clear()
            return

        pixmap = QPixmap(icon_path)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                48, 48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.icon_preview_label.setPixmap(scaled_pixmap)
        else:
            self.icon_preview_label.clear()
