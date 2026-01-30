#!/usr/bin/env python3
"""
스키마 한국어 명칭 검증 GUI
모든 게임의 재화/콘텐츠/UI 요소 한국어 명칭을 검증하고 수정하는 도구
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QComboBox,
    QLabel, QHeaderView, QCheckBox, QTextEdit, QMessageBox,
    QDialog, QDialogButtonBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor


# 프로젝트 루트 디렉토리
ROOT_DIR = Path(__file__).parent.parent
SCHEMAS_DIR = ROOT_DIR / "schemas"
GAMES_DIR = SCHEMAS_DIR / "games"


class SchemaItemEditDialog(QDialog):
    """개별 항목 편집 다이얼로그"""

    def __init__(self, item_data: dict, parent=None):
        super().__init__(parent)
        self.item_data = item_data.copy()
        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle("항목 편집")
        self.setMinimumWidth(500)

        layout = QVBoxLayout()

        # ID (읽기 전용)
        id_layout = QHBoxLayout()
        id_layout.addWidget(QLabel("ID:"))
        id_label = QLabel(self.item_data.get('id', ''))
        id_label.setStyleSheet("font-weight: bold;")
        id_layout.addWidget(id_label)
        id_layout.addStretch()
        layout.addLayout(id_layout)

        # 영어명 (읽기 전용)
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("영어명:"))
        name_label = QLabel(self.item_data.get('name', ''))
        name_layout.addWidget(name_label)
        name_layout.addStretch()
        layout.addLayout(name_layout)

        # 한국어명 (편집 가능)
        kr_layout = QVBoxLayout()
        kr_layout.addWidget(QLabel("한국어명:"))
        self.kr_edit = QTextEdit()
        self.kr_edit.setPlainText(self.item_data.get('name_kr', ''))
        self.kr_edit.setMaximumHeight(60)
        kr_layout.addWidget(self.kr_edit)
        layout.addLayout(kr_layout)

        # 검증 완료 체크박스
        self.verified_checkbox = QCheckBox("검증 완료")
        self.verified_checkbox.setChecked(self.item_data.get('name_kr_verified', False))
        layout.addWidget(self.verified_checkbox)

        # 메모 (편집 가능)
        note_layout = QVBoxLayout()
        note_layout.addWidget(QLabel("메모:"))
        self.note_edit = QTextEdit()
        self.note_edit.setPlainText(self.item_data.get('verification_note', ''))
        self.note_edit.setMaximumHeight(80)
        note_layout.addWidget(self.note_edit)
        layout.addLayout(note_layout)

        # 버튼
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def get_updated_data(self) -> dict:
        """수정된 데이터 반환"""
        self.item_data['name_kr'] = self.kr_edit.toPlainText().strip()
        self.item_data['name_kr_verified'] = self.verified_checkbox.isChecked()
        self.item_data['verification_note'] = self.note_edit.toPlainText().strip()
        return self.item_data


class SchemaVerifierGUI(QMainWindow):
    """스키마 검증 메인 윈도우"""

    def __init__(self):
        super().__init__()
        self.current_game_id = None
        self.current_schema_type = None
        self.schema_data = {}
        self.modified = False

        self.setup_ui()
        self.load_games()

    def setup_ui(self):
        """UI 초기화"""
        self.setWindowTitle("스키마 한국어 명칭 검증 도구")
        self.setMinimumSize(1000, 600)

        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)

        # 상단 컨트롤
        controls_layout = QHBoxLayout()

        # 게임 선택
        controls_layout.addWidget(QLabel("게임:"))
        self.game_combo = QComboBox()
        self.game_combo.currentTextChanged.connect(self.on_game_changed)
        controls_layout.addWidget(self.game_combo)

        # 스키마 타입 선택
        controls_layout.addWidget(QLabel("타입:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["재화 (Resources)", "콘텐츠 (Contents)", "UI 요소 (UI Elements)"])
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        controls_layout.addWidget(self.type_combo)

        controls_layout.addStretch()

        # 통계 라벨
        self.stats_label = QLabel("총 0개 항목 | 검증 완료: 0개")
        controls_layout.addWidget(self.stats_label)

        main_layout.addLayout(controls_layout)

        # 테이블
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "ID", "영어명", "한국어명", "검증 완료", "메모", "편집"
        ])

        # 테이블 설정
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        main_layout.addWidget(self.table)

        # 하단 버튼
        button_layout = QHBoxLayout()

        # 모두 검증 완료 버튼
        verify_all_btn = QPushButton("모두 검증 완료 처리")
        verify_all_btn.clicked.connect(self.verify_all)
        button_layout.addWidget(verify_all_btn)

        button_layout.addStretch()

        # 저장 버튼
        save_btn = QPushButton("💾 저장")
        save_btn.setStyleSheet("font-weight: bold; padding: 8px 20px;")
        save_btn.clicked.connect(self.save_changes)
        button_layout.addWidget(save_btn)

        # 새로고침 버튼
        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.clicked.connect(self.refresh_current)
        button_layout.addWidget(refresh_btn)

        main_layout.addLayout(button_layout)

    def load_games(self):
        """게임 목록 로드"""
        registry_file = SCHEMAS_DIR / "registry.json"

        if not registry_file.exists():
            QMessageBox.critical(self, "오류", "registry.json 파일을 찾을 수 없습니다.")
            return

        with open(registry_file, 'r', encoding='utf-8') as f:
            registry = json.load(f)

        for game in registry['games']:
            self.game_combo.addItem(
                f"{game['game_name_kr']} ({game['game_id']})",
                game['game_id']
            )

    def on_game_changed(self, text):
        """게임 선택 변경"""
        if not text:
            return

        self.current_game_id = self.game_combo.currentData()
        self.load_schema()

    def on_type_changed(self, text):
        """스키마 타입 변경"""
        type_map = {
            "재화 (Resources)": "resources",
            "콘텐츠 (Contents)": "contents",
            "UI 요소 (UI Elements)": "ui_elements"
        }

        self.current_schema_type = type_map.get(text)
        self.load_schema()

    def load_schema(self):
        """현재 선택된 스키마 로드"""
        if not self.current_game_id or not self.current_schema_type:
            return

        schema_file = GAMES_DIR / self.current_game_id / f"{self.current_schema_type}.json"

        if not schema_file.exists():
            QMessageBox.warning(self, "경고", f"스키마 파일을 찾을 수 없습니다:\n{schema_file}")
            return

        with open(schema_file, 'r', encoding='utf-8') as f:
            self.schema_data = json.load(f)

        self.populate_table()
        self.update_stats()

    def populate_table(self):
        """테이블 채우기"""
        # 데이터 키 결정
        data_key = self.current_schema_type
        if data_key == "ui_elements":
            data_key = "ui_elements"

        items = self.schema_data.get(data_key, [])

        self.table.setRowCount(len(items))

        for row, item in enumerate(items):
            # ID
            id_item = QTableWidgetItem(item.get('id', ''))
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, id_item)

            # 영어명
            name_item = QTableWidgetItem(item.get('name', ''))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, name_item)

            # 한국어명
            kr_name_item = QTableWidgetItem(item.get('name_kr', ''))
            kr_name_item.setFlags(kr_name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 2, kr_name_item)

            # 검증 완료
            verified = item.get('name_kr_verified', False)
            verified_item = QTableWidgetItem("✅" if verified else "❌")
            verified_item.setFlags(verified_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if verified:
                verified_item.setBackground(QColor(200, 255, 200))
            else:
                verified_item.setBackground(QColor(255, 200, 200))
            self.table.setItem(row, 3, verified_item)

            # 메모
            note_item = QTableWidgetItem(item.get('verification_note', ''))
            note_item.setFlags(note_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 4, note_item)

            # 편집 버튼
            edit_btn = QPushButton("✏️ 편집")
            edit_btn.clicked.connect(lambda checked, r=row: self.edit_item(r))
            self.table.setCellWidget(row, 5, edit_btn)

    def edit_item(self, row: int):
        """항목 편집"""
        data_key = self.current_schema_type
        items = self.schema_data.get(data_key, [])

        if row >= len(items):
            return

        item = items[row]

        dialog = SchemaItemEditDialog(item, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_data = dialog.get_updated_data()
            items[row] = updated_data
            self.modified = True
            self.populate_table()
            self.update_stats()

    def verify_all(self):
        """모든 항목 검증 완료 처리"""
        reply = QMessageBox.question(
            self,
            "확인",
            "현재 표시된 모든 항목을 검증 완료 상태로 변경하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            data_key = self.current_schema_type
            items = self.schema_data.get(data_key, [])

            for item in items:
                item['name_kr_verified'] = True
                if not item.get('verification_note'):
                    item['verification_note'] = "일괄 검증 완료"

            self.modified = True
            self.populate_table()
            self.update_stats()
            QMessageBox.information(self, "완료", f"{len(items)}개 항목이 검증 완료 처리되었습니다.")

    def update_stats(self):
        """통계 업데이트"""
        data_key = self.current_schema_type
        items = self.schema_data.get(data_key, [])

        total = len(items)
        verified = sum(1 for item in items if item.get('name_kr_verified', False))

        self.stats_label.setText(f"총 {total}개 항목 | 검증 완료: {verified}개 ({verified/total*100:.1f}%)")

    def refresh_current(self):
        """현재 스키마 새로고침"""
        if self.modified:
            reply = QMessageBox.question(
                self,
                "확인",
                "저장하지 않은 변경사항이 있습니다. 새로고침하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.No:
                return

        self.modified = False
        self.load_schema()

    def save_changes(self):
        """변경사항 저장"""
        if not self.current_game_id or not self.current_schema_type:
            return

        schema_file = GAMES_DIR / self.current_game_id / f"{self.current_schema_type}.json"

        try:
            with open(schema_file, 'w', encoding='utf-8') as f:
                json.dump(self.schema_data, f, ensure_ascii=False, indent=2)

            self.modified = False
            QMessageBox.information(self, "성공", "변경사항이 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "오류", f"저장 중 오류 발생:\n{e}")

    def closeEvent(self, event):
        """종료 시 확인"""
        if self.modified:
            reply = QMessageBox.question(
                self,
                "확인",
                "저장하지 않은 변경사항이 있습니다. 종료하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

        event.accept()


def main():
    """메인 실행 함수"""
    app = QApplication(sys.argv)
    window = SchemaVerifierGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
