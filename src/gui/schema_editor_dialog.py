#!/usr/bin/env python3
"""
게임 스키마 편집 대화상자
재화(Resources), 콘텐츠(Contents), UI 요소(UI Elements)를 편집할 수 있는 통합 에디터
"""

from typing import Optional, Dict, Any, List
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QPushButton, QDialogButtonBox,
    QHeaderView, QMessageBox, QFormLayout, QLineEdit, QSpinBox,
    QCheckBox, QComboBox, QTextEdit, QLabel, QGroupBox
)
from PyQt6.QtCore import Qt


# 스키마 유틸리티 import
try:
    from src.schema import load_game_schema, save_game_schema, get_game_info
    SCHEMA_SUPPORT = True
except ImportError:
    SCHEMA_SUPPORT = False
    def load_game_schema(game_id, schema_type):
        return None
    def save_game_schema(game_id, schema_type, data):
        return False
    def get_game_info(game_id):
        return None


class ResourceEditDialog(QDialog):
    """재화 항목 편집 대화상자"""
    def __init__(self, parent=None, resource_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle("재화 편집" if resource_data else "새 재화 추가")
        self.setMinimumWidth(400)

        layout = QFormLayout(self)

        self.id_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.name_kr_edit = QLineEdit()
        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "currency", "premium_currency", "gacha_ticket",
            "stamina", "upgrade_material", "special_item"
        ])
        self.description_edit = QLineEdit()
        self.max_value_spin = QSpinBox()
        self.max_value_spin.setRange(0, 999999999)
        self.max_value_spin.setValue(999999)
        self.ocr_pattern_edit = QLineEdit()
        self.ocr_pattern_edit.setPlaceholderText("예: ^[0-9,]+$")

        layout.addRow("ID (영문):", self.id_edit)
        layout.addRow("이름 (영문):", self.name_edit)
        layout.addRow("이름 (한국어):", self.name_kr_edit)
        layout.addRow("카테고리:", self.category_combo)
        layout.addRow("설명:", self.description_edit)
        layout.addRow("최대값:", self.max_value_spin)
        layout.addRow("OCR 패턴:", self.ocr_pattern_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        # 기존 데이터 로드
        if resource_data:
            self.id_edit.setText(resource_data.get("id", ""))
            self.name_edit.setText(resource_data.get("name", ""))
            self.name_kr_edit.setText(resource_data.get("name_kr", ""))
            cat = resource_data.get("category", "currency")
            idx = self.category_combo.findText(cat)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            self.description_edit.setText(resource_data.get("description", ""))
            self.max_value_spin.setValue(resource_data.get("max_value", 999999))
            self.ocr_pattern_edit.setText(resource_data.get("ocr_pattern", "^[0-9,]+$"))

    def validate_and_accept(self):
        if not self.id_edit.text().strip():
            QMessageBox.warning(self, "입력 오류", "ID를 입력해야 합니다.")
            return
        if not self.name_kr_edit.text().strip():
            QMessageBox.warning(self, "입력 오류", "한국어 이름을 입력해야 합니다.")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        return {
            "id": self.id_edit.text().strip(),
            "name": self.name_edit.text().strip() or self.id_edit.text().strip(),
            "name_kr": self.name_kr_edit.text().strip(),
            "category": self.category_combo.currentText(),
            "description": self.description_edit.text().strip(),
            "max_value": self.max_value_spin.value(),
            "ocr_pattern": self.ocr_pattern_edit.text().strip() or "^[0-9,]+$"
        }


class ContentEditDialog(QDialog):
    """콘텐츠 항목 편집 대화상자"""
    def __init__(self, parent=None, content_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle("콘텐츠 편집" if content_data else "새 콘텐츠 추가")
        self.setMinimumWidth(450)

        layout = QFormLayout(self)

        self.id_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.name_kr_edit = QLineEdit()
        self.category_combo = QComboBox()
        self.category_combo.addItems(["daily", "weekly", "event", "permanent", "special"])
        self.description_edit = QLineEdit()
        self.reset_time_edit = QLineEdit()
        self.reset_time_edit.setPlaceholderText("HH:MM (예: 04:00)")
        self.max_count_spin = QSpinBox()
        self.max_count_spin.setRange(0, 9999)
        self.stamina_cost_spin = QSpinBox()
        self.stamina_cost_spin.setRange(0, 9999)
        self.rewards_edit = QLineEdit()
        self.rewards_edit.setPlaceholderText("쉼표로 구분 (예: polychrome,dennies)")
        self.ui_indicators_edit = QLineEdit()
        self.ui_indicators_edit.setPlaceholderText("쉼표로 구분")

        layout.addRow("ID (영문):", self.id_edit)
        layout.addRow("이름 (영문):", self.name_edit)
        layout.addRow("이름 (한국어):", self.name_kr_edit)
        layout.addRow("카테고리:", self.category_combo)
        layout.addRow("설명:", self.description_edit)
        layout.addRow("초기화 시각:", self.reset_time_edit)
        layout.addRow("최대 횟수:", self.max_count_spin)
        layout.addRow("스태미나 비용:", self.stamina_cost_spin)
        layout.addRow("보상 재화:", self.rewards_edit)
        layout.addRow("UI 표시기:", self.ui_indicators_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        # 기존 데이터 로드
        if content_data:
            self.id_edit.setText(content_data.get("id", ""))
            self.name_edit.setText(content_data.get("name", ""))
            self.name_kr_edit.setText(content_data.get("name_kr", ""))
            cat = content_data.get("category", "daily")
            idx = self.category_combo.findText(cat)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            self.description_edit.setText(content_data.get("description", ""))
            self.reset_time_edit.setText(content_data.get("reset_time", ""))
            self.max_count_spin.setValue(content_data.get("max_count", 0))
            self.stamina_cost_spin.setValue(content_data.get("stamina_cost", 0))
            rewards = content_data.get("rewards", [])
            self.rewards_edit.setText(",".join(rewards) if rewards else "")
            indicators = content_data.get("ui_indicators", [])
            self.ui_indicators_edit.setText(",".join(indicators) if indicators else "")

    def validate_and_accept(self):
        if not self.id_edit.text().strip():
            QMessageBox.warning(self, "입력 오류", "ID를 입력해야 합니다.")
            return
        if not self.name_kr_edit.text().strip():
            QMessageBox.warning(self, "입력 오류", "한국어 이름을 입력해야 합니다.")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        rewards_str = self.rewards_edit.text().strip()
        rewards = [r.strip() for r in rewards_str.split(",") if r.strip()] if rewards_str else []

        indicators_str = self.ui_indicators_edit.text().strip()
        indicators = [i.strip() for i in indicators_str.split(",") if i.strip()] if indicators_str else []

        data = {
            "id": self.id_edit.text().strip(),
            "name": self.name_edit.text().strip() or self.id_edit.text().strip(),
            "name_kr": self.name_kr_edit.text().strip(),
            "category": self.category_combo.currentText(),
            "description": self.description_edit.text().strip(),
            "reset_time": self.reset_time_edit.text().strip(),
            "rewards": rewards,
            "ui_indicators": indicators,
        }

        # 선택적 필드
        if self.max_count_spin.value() > 0:
            data["max_count"] = self.max_count_spin.value()
        if self.stamina_cost_spin.value() > 0:
            data["stamina_cost"] = self.stamina_cost_spin.value()

        return data


class UIElementEditDialog(QDialog):
    """UI 요소 항목 편집 대화상자"""
    def __init__(self, parent=None, element_data: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setWindowTitle("UI 요소 편집" if element_data else "새 UI 요소 추가")
        self.setMinimumWidth(450)

        layout = QFormLayout(self)

        self.id_edit = QLineEdit()
        self.name_edit = QLineEdit()
        self.name_kr_edit = QLineEdit()
        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "hud", "quest", "menu", "dialog", "popup", "button", "indicator"
        ])
        self.description_edit = QLineEdit()
        self.always_visible_check = QCheckBox()
        self.contains_ocr_check = QCheckBox()
        self.ocr_targets_edit = QLineEdit()
        self.ocr_targets_edit.setPlaceholderText("쉼표로 구분 (예: dennies,polychrome)")
        self.typical_position_combo = QComboBox()
        self.typical_position_combo.addItems([
            "top_left", "top_center", "top_right",
            "center_left", "center", "center_right",
            "bottom_left", "bottom_center", "bottom_right",
            "left_side", "right_side", "fullscreen"
        ])
        self.yolo_class_name_edit = QLineEdit()
        self.yolo_class_name_edit.setPlaceholderText("YOLO 모델의 클래스 이름")

        layout.addRow("ID (영문):", self.id_edit)
        layout.addRow("이름 (영문):", self.name_edit)
        layout.addRow("이름 (한국어):", self.name_kr_edit)
        layout.addRow("카테고리:", self.category_combo)
        layout.addRow("설명:", self.description_edit)
        layout.addRow("항상 표시:", self.always_visible_check)
        layout.addRow("OCR 포함:", self.contains_ocr_check)
        layout.addRow("OCR 대상:", self.ocr_targets_edit)
        layout.addRow("일반 위치:", self.typical_position_combo)
        layout.addRow("YOLO 클래스:", self.yolo_class_name_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        # 기존 데이터 로드
        if element_data:
            self.id_edit.setText(element_data.get("id", ""))
            self.name_edit.setText(element_data.get("name", ""))
            self.name_kr_edit.setText(element_data.get("name_kr", ""))
            cat = element_data.get("category", "hud")
            idx = self.category_combo.findText(cat)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            self.description_edit.setText(element_data.get("description", ""))
            self.always_visible_check.setChecked(element_data.get("always_visible", False))
            self.contains_ocr_check.setChecked(element_data.get("contains_ocr", False))
            targets = element_data.get("ocr_targets", [])
            self.ocr_targets_edit.setText(",".join(targets) if targets else "")
            pos = element_data.get("typical_position", "center")
            pos_idx = self.typical_position_combo.findText(pos)
            if pos_idx >= 0:
                self.typical_position_combo.setCurrentIndex(pos_idx)
            self.yolo_class_name_edit.setText(element_data.get("yolo_class_name", ""))

    def validate_and_accept(self):
        if not self.id_edit.text().strip():
            QMessageBox.warning(self, "입력 오류", "ID를 입력해야 합니다.")
            return
        if not self.name_kr_edit.text().strip():
            QMessageBox.warning(self, "입력 오류", "한국어 이름을 입력해야 합니다.")
            return
        self.accept()

    def get_data(self) -> Dict[str, Any]:
        targets_str = self.ocr_targets_edit.text().strip()
        targets = [t.strip() for t in targets_str.split(",") if t.strip()] if targets_str else []

        return {
            "id": self.id_edit.text().strip(),
            "name": self.name_edit.text().strip() or self.id_edit.text().strip(),
            "name_kr": self.name_kr_edit.text().strip(),
            "category": self.category_combo.currentText(),
            "description": self.description_edit.text().strip(),
            "always_visible": self.always_visible_check.isChecked(),
            "contains_ocr": self.contains_ocr_check.isChecked(),
            "ocr_targets": targets,
            "typical_position": self.typical_position_combo.currentText(),
            "yolo_class_name": self.yolo_class_name_edit.text().strip()
        }


class SchemaEditorDialog(QDialog):
    """게임 스키마 통합 편집 대화상자"""

    def __init__(self, game_id: str, parent=None):
        super().__init__(parent)
        self.game_id = game_id
        self.setWindowTitle(f"스키마 편집기 - {game_id}")
        self.setMinimumSize(800, 600)

        # 스키마 데이터 로드
        self.resources_data = load_game_schema(game_id, "resources") or self._create_empty_schema("resources")
        self.contents_data = load_game_schema(game_id, "contents") or self._create_empty_schema("contents")
        self.ui_elements_data = load_game_schema(game_id, "ui_elements") or self._create_empty_schema("ui_elements")

        self._setup_ui()
        self._load_data_to_tables()

    def _create_empty_schema(self, schema_type: str) -> Dict[str, Any]:
        """빈 스키마 생성"""
        game_info = get_game_info(self.game_id) or {}
        base = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "version": "1.0.0",
            "game_id": self.game_id,
            "game_name": game_info.get("game_name", self.game_id),
            "game_name_kr": game_info.get("game_name_kr", self.game_id),
        }

        if schema_type == "resources":
            base["title"] = "Game Resources"
            base["description"] = f"{base['game_name_kr']} 재화 정의"
            base["resources"] = []
        elif schema_type == "contents":
            base["title"] = "Game Contents"
            base["description"] = f"{base['game_name_kr']} 콘텐츠 정의"
            base["contents"] = []
        elif schema_type == "ui_elements":
            base["title"] = "UI Elements"
            base["description"] = f"{base['game_name_kr']} UI 요소 정의"
            base["ui_elements"] = []

        return base

    def _setup_ui(self):
        """UI 설정"""
        main_layout = QVBoxLayout(self)

        # 게임 정보 표시
        game_info = get_game_info(self.game_id) or {}
        game_name_kr = game_info.get("game_name_kr", self.game_id)
        info_label = QLabel(f"게임: {game_name_kr} ({self.game_id})")
        info_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        main_layout.addWidget(info_label)

        # 탭 위젯
        self.tab_widget = QTabWidget()

        # 재화 탭
        self.resources_tab = self._create_resources_tab()
        self.tab_widget.addTab(self.resources_tab, "재화 (Resources)")

        # 콘텐츠 탭
        self.contents_tab = self._create_contents_tab()
        self.tab_widget.addTab(self.contents_tab, "콘텐츠 (Contents)")

        # UI 요소 탭
        self.ui_elements_tab = self._create_ui_elements_tab()
        self.tab_widget.addTab(self.ui_elements_tab, "UI 요소 (Elements)")

        main_layout.addWidget(self.tab_widget)

        # 하단 버튼
        button_layout = QHBoxLayout()

        self.save_button = QPushButton("저장")
        self.save_button.clicked.connect(self._save_all)
        button_layout.addWidget(self.save_button)

        self.close_button = QPushButton("닫기")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        main_layout.addLayout(button_layout)

    def _create_resources_tab(self) -> QWidget:
        """재화 탭 생성"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # 테이블
        self.resources_table = QTableWidget()
        self.resources_table.setColumnCount(5)
        self.resources_table.setHorizontalHeaderLabels(["ID", "한국어 이름", "카테고리", "설명", "최대값"])
        self.resources_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.resources_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.resources_table.horizontalHeader()
        if header:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.resources_table)

        # 버튼
        button_layout = QHBoxLayout()
        add_btn = QPushButton("추가")
        add_btn.clicked.connect(self._add_resource)
        edit_btn = QPushButton("편집")
        edit_btn.clicked.connect(self._edit_resource)
        remove_btn = QPushButton("삭제")
        remove_btn.clicked.connect(self._remove_resource)

        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(remove_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        return tab

    def _create_contents_tab(self) -> QWidget:
        """콘텐츠 탭 생성"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.contents_table = QTableWidget()
        self.contents_table.setColumnCount(5)
        self.contents_table.setHorizontalHeaderLabels(["ID", "한국어 이름", "카테고리", "초기화 시각", "설명"])
        self.contents_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.contents_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.contents_table.horizontalHeader()
        if header:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.contents_table)

        button_layout = QHBoxLayout()
        add_btn = QPushButton("추가")
        add_btn.clicked.connect(self._add_content)
        edit_btn = QPushButton("편집")
        edit_btn.clicked.connect(self._edit_content)
        remove_btn = QPushButton("삭제")
        remove_btn.clicked.connect(self._remove_content)

        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(remove_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        return tab

    def _create_ui_elements_tab(self) -> QWidget:
        """UI 요소 탭 생성"""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.ui_elements_table = QTableWidget()
        self.ui_elements_table.setColumnCount(5)
        self.ui_elements_table.setHorizontalHeaderLabels(["ID", "한국어 이름", "카테고리", "YOLO 클래스", "OCR 포함"])
        self.ui_elements_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ui_elements_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.ui_elements_table.horizontalHeader()
        if header:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.ui_elements_table)

        button_layout = QHBoxLayout()
        add_btn = QPushButton("추가")
        add_btn.clicked.connect(self._add_ui_element)
        edit_btn = QPushButton("편집")
        edit_btn.clicked.connect(self._edit_ui_element)
        remove_btn = QPushButton("삭제")
        remove_btn.clicked.connect(self._remove_ui_element)

        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(remove_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        return tab

    def _load_data_to_tables(self):
        """테이블에 데이터 로드"""
        # 재화 테이블
        resources = self.resources_data.get("resources", [])
        self.resources_table.setRowCount(len(resources))
        for row, res in enumerate(resources):
            self.resources_table.setItem(row, 0, QTableWidgetItem(res.get("id", "")))
            self.resources_table.setItem(row, 1, QTableWidgetItem(res.get("name_kr", "")))
            self.resources_table.setItem(row, 2, QTableWidgetItem(res.get("category", "")))
            self.resources_table.setItem(row, 3, QTableWidgetItem(res.get("description", "")))
            self.resources_table.setItem(row, 4, QTableWidgetItem(str(res.get("max_value", 0))))

        # 콘텐츠 테이블
        contents = self.contents_data.get("contents", [])
        self.contents_table.setRowCount(len(contents))
        for row, cont in enumerate(contents):
            self.contents_table.setItem(row, 0, QTableWidgetItem(cont.get("id", "")))
            self.contents_table.setItem(row, 1, QTableWidgetItem(cont.get("name_kr", "")))
            self.contents_table.setItem(row, 2, QTableWidgetItem(cont.get("category", "")))
            self.contents_table.setItem(row, 3, QTableWidgetItem(cont.get("reset_time", "")))
            self.contents_table.setItem(row, 4, QTableWidgetItem(cont.get("description", "")))

        # UI 요소 테이블
        ui_elements = self.ui_elements_data.get("ui_elements", [])
        self.ui_elements_table.setRowCount(len(ui_elements))
        for row, elem in enumerate(ui_elements):
            self.ui_elements_table.setItem(row, 0, QTableWidgetItem(elem.get("id", "")))
            self.ui_elements_table.setItem(row, 1, QTableWidgetItem(elem.get("name_kr", "")))
            self.ui_elements_table.setItem(row, 2, QTableWidgetItem(elem.get("category", "")))
            self.ui_elements_table.setItem(row, 3, QTableWidgetItem(elem.get("yolo_class_name", "")))
            self.ui_elements_table.setItem(row, 4, QTableWidgetItem("예" if elem.get("contains_ocr", False) else "아니오"))

    # === 재화 CRUD ===
    def _add_resource(self):
        dialog = ResourceEditDialog(self)
        if dialog.exec():
            new_data = dialog.get_data()
            self.resources_data["resources"].append(new_data)
            self._refresh_resources_table()

    def _edit_resource(self):
        row = self.resources_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "편집할 항목을 선택하세요.")
            return

        current_data = self.resources_data["resources"][row]
        dialog = ResourceEditDialog(self, current_data)
        if dialog.exec():
            self.resources_data["resources"][row] = dialog.get_data()
            self._refresh_resources_table()

    def _remove_resource(self):
        row = self.resources_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "삭제할 항목을 선택하세요.")
            return

        reply = QMessageBox.question(
            self, "삭제 확인", "선택한 재화를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.resources_data["resources"][row]
            self._refresh_resources_table()

    def _refresh_resources_table(self):
        self._load_data_to_tables()  # 전체 테이블 갱신

    # === 콘텐츠 CRUD ===
    def _add_content(self):
        dialog = ContentEditDialog(self)
        if dialog.exec():
            new_data = dialog.get_data()
            self.contents_data["contents"].append(new_data)
            self._load_data_to_tables()

    def _edit_content(self):
        row = self.contents_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "편집할 항목을 선택하세요.")
            return

        current_data = self.contents_data["contents"][row]
        dialog = ContentEditDialog(self, current_data)
        if dialog.exec():
            self.contents_data["contents"][row] = dialog.get_data()
            self._load_data_to_tables()

    def _remove_content(self):
        row = self.contents_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "삭제할 항목을 선택하세요.")
            return

        reply = QMessageBox.question(
            self, "삭제 확인", "선택한 콘텐츠를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.contents_data["contents"][row]
            self._load_data_to_tables()

    # === UI 요소 CRUD ===
    def _add_ui_element(self):
        dialog = UIElementEditDialog(self)
        if dialog.exec():
            new_data = dialog.get_data()
            self.ui_elements_data["ui_elements"].append(new_data)
            self._load_data_to_tables()

    def _edit_ui_element(self):
        row = self.ui_elements_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "편집할 항목을 선택하세요.")
            return

        current_data = self.ui_elements_data["ui_elements"][row]
        dialog = UIElementEditDialog(self, current_data)
        if dialog.exec():
            self.ui_elements_data["ui_elements"][row] = dialog.get_data()
            self._load_data_to_tables()

    def _remove_ui_element(self):
        row = self.ui_elements_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "선택 오류", "삭제할 항목을 선택하세요.")
            return

        reply = QMessageBox.question(
            self, "삭제 확인", "선택한 UI 요소를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.ui_elements_data["ui_elements"][row]
            self._load_data_to_tables()

    def _save_all(self):
        """모든 스키마 저장"""
        success = True

        if not save_game_schema(self.game_id, "resources", self.resources_data):
            success = False
        if not save_game_schema(self.game_id, "contents", self.contents_data):
            success = False
        if not save_game_schema(self.game_id, "ui_elements", self.ui_elements_data):
            success = False

        if success:
            QMessageBox.information(self, "저장 완료", "모든 스키마가 저장되었습니다.")
        else:
            QMessageBox.warning(self, "저장 오류", "일부 스키마 저장에 실패했습니다.")
