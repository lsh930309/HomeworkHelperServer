#!/usr/bin/env python3
"""
로그 뷰어 위젯
실시간 로그 표시 및 필터링 기능
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QComboBox, QCheckBox, QLabel
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QTextCursor, QColor, QTextCharFormat
from typing import List, Optional
from datetime import datetime


class LogViewer(QWidget):
    """로그 뷰어 위젯"""

    LOG_LEVEL_ALL = "전체"
    LOG_LEVEL_ERROR = "에러만"
    LOG_LEVEL_WARNING = "경고만"
    LOG_LEVEL_INFO = "정보만"

    def __init__(self, max_lines: int = 1000, parent=None):
        """
        로그 뷰어 초기화

        Args:
            max_lines: 최대 로그 줄 수
            parent: 부모 위젯
        """
        super().__init__(parent)
        self.max_lines = max_lines
        self.log_buffer: List[str] = []
        self.auto_scroll = True

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 상단 컨트롤 바
        control_layout = QHBoxLayout()

        # 로그 레벨 필터
        control_layout.addWidget(QLabel("필터:"))
        self.level_filter = QComboBox()
        self.level_filter.addItems([
            self.LOG_LEVEL_ALL,
            self.LOG_LEVEL_ERROR,
            self.LOG_LEVEL_WARNING,
            self.LOG_LEVEL_INFO
        ])
        self.level_filter.currentTextChanged.connect(self.apply_filter)
        control_layout.addWidget(self.level_filter)

        # 자동 스크롤 체크박스
        self.auto_scroll_checkbox = QCheckBox("자동 스크롤")
        self.auto_scroll_checkbox.setChecked(True)
        self.auto_scroll_checkbox.stateChanged.connect(self._on_auto_scroll_changed)
        control_layout.addWidget(self.auto_scroll_checkbox)

        control_layout.addStretch()

        # 지우기 버튼
        self.clear_button = QPushButton("로그 지우기")
        self.clear_button.clicked.connect(self.clear_logs)
        control_layout.addWidget(self.clear_button)

        layout.addLayout(control_layout)

        # 로그 텍스트 에디터
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        # 폰트 설정 (고정폭)
        font = self.log_text.font()
        font.setFamily("Consolas")
        font.setPointSize(9)
        self.log_text.setFont(font)

        layout.addWidget(self.log_text)

        self.setLayout(layout)

    def add_log(self, message: str, level: str = "INFO"):
        """
        로그 추가

        Args:
            message: 로그 메시지
            level: 로그 레벨 (INFO, WARNING, ERROR)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [{level}] {message}"

        self.log_buffer.append(log_line)

        # 최대 줄 수 제한
        if len(self.log_buffer) > self.max_lines:
            self.log_buffer.pop(0)

        # 필터 적용하여 표시
        self.apply_filter()

    def add_log_lines(self, lines: List[str]):
        """
        여러 줄 로그 추가 (Docker 로그 등)

        Args:
            lines: 로그 라인 리스트
        """
        for line in lines:
            # 로그 레벨 추정
            line_lower = line.lower()
            if 'error' in line_lower or 'exception' in line_lower:
                level = "ERROR"
            elif 'warn' in line_lower:
                level = "WARNING"
            else:
                level = "INFO"

            self.add_log(line, level)

    def clear_logs(self):
        """로그 지우기"""
        self.log_buffer.clear()
        self.log_text.clear()

    def apply_filter(self):
        """로그 필터 적용"""
        filter_level = self.level_filter.currentText()

        self.log_text.clear()

        for log_line in self.log_buffer:
            # 필터링
            if filter_level == self.LOG_LEVEL_ALL:
                should_show = True
            elif filter_level == self.LOG_LEVEL_ERROR:
                should_show = "[ERROR]" in log_line
            elif filter_level == self.LOG_LEVEL_WARNING:
                should_show = "[WARNING]" in log_line
            elif filter_level == self.LOG_LEVEL_INFO:
                should_show = "[INFO]" in log_line
            else:
                should_show = True

            if should_show:
                self._append_colored_log(log_line)

        # 자동 스크롤
        if self.auto_scroll:
            self.scroll_to_bottom()

    def _append_colored_log(self, log_line: str):
        """
        색상 적용하여 로그 추가

        Args:
            log_line: 로그 라인
        """
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # 로그 레벨에 따라 색상 설정
        format = QTextCharFormat()
        if "[ERROR]" in log_line:
            format.setForeground(QColor(255, 100, 100))  # 빨강
        elif "[WARNING]" in log_line:
            format.setForeground(QColor(255, 200, 100))  # 주황
        elif "[INFO]" in log_line:
            format.setForeground(QColor(200, 200, 200))  # 회색
        else:
            format.setForeground(QColor(255, 255, 255))  # 흰색

        cursor.insertText(log_line + "\n", format)

    def scroll_to_bottom(self):
        """로그 맨 아래로 스크롤"""
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_auto_scroll_changed(self, state):
        """자동 스크롤 상태 변경"""
        self.auto_scroll = (state == Qt.CheckState.Checked.value)

    def get_error_count(self) -> int:
        """에러 로그 개수 반환"""
        return sum(1 for log in self.log_buffer if "[ERROR]" in log)

    def get_warning_count(self) -> int:
        """경고 로그 개수 반환"""
        return sum(1 for log in self.log_buffer if "[WARNING]" in log)

    def save_logs(self, file_path: str) -> bool:
        """
        로그를 파일로 저장

        Args:
            file_path: 저장할 파일 경로

        Returns:
            성공 여부
        """
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(self.log_buffer))
            return True
        except Exception as e:
            print(f"로그 저장 실패: {e}")
            return False
