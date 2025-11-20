#!/usr/bin/env python3
"""
상태 표시기 위젯
Docker 및 Label Studio 상태를 시각적으로 표시
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QBrush
from enum import Enum


class StatusState(Enum):
    """상태"""
    RUNNING = "running"  # 실행 중 (녹색)
    STOPPED = "stopped"  # 중지됨 (회색)
    ERROR = "error"      # 에러 (빨강)
    WARNING = "warning"  # 경고 (주황)


class StatusIndicator(QWidget):
    """상태 표시기 위젯 (원형 인디케이터 + 텍스트)"""

    COLOR_RUNNING = QColor(100, 200, 100)  # 녹색
    COLOR_STOPPED = QColor(150, 150, 150)  # 회색
    COLOR_ERROR = QColor(255, 100, 100)    # 빨강
    COLOR_WARNING = QColor(255, 200, 100)  # 주황

    def __init__(self, label: str = "", parent=None):
        """
        상태 표시기 초기화

        Args:
            label: 레이블 텍스트
            parent: 부모 위젯
        """
        super().__init__(parent)

        self.state = StatusState.STOPPED
        self.label_text = label

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # 레이블
        self.label = QLabel(self.label_text)
        layout.addWidget(self.label)

        # 상태 원형 (paintEvent에서 그림)
        self.indicator = QLabel()
        self.indicator.setFixedSize(16, 16)
        layout.addWidget(self.indicator)

        # 상태 텍스트
        self.status_text = QLabel("중지됨")
        layout.addWidget(self.status_text)

        layout.addStretch()

        self.setLayout(layout)

        # 초기 업데이트
        self.update_display()

    def set_state(self, state: StatusState, text: str = ""):
        """
        상태 설정

        Args:
            state: 상태
            text: 상태 텍스트 (None이면 기본값 사용)
        """
        self.state = state

        if text:
            self.status_text.setText(text)
        else:
            # 기본 텍스트
            if state == StatusState.RUNNING:
                self.status_text.setText("실행 중")
            elif state == StatusState.STOPPED:
                self.status_text.setText("중지됨")
            elif state == StatusState.ERROR:
                self.status_text.setText("에러")
            elif state == StatusState.WARNING:
                self.status_text.setText("경고")

        self.update_display()

    def update_display(self):
        """화면 업데이트"""
        # 상태에 따른 색상 설정
        if self.state == StatusState.RUNNING:
            color = self.COLOR_RUNNING
        elif self.state == StatusState.STOPPED:
            color = self.COLOR_STOPPED
        elif self.state == StatusState.ERROR:
            color = self.COLOR_ERROR
        elif self.state == StatusState.WARNING:
            color = self.COLOR_WARNING
        else:
            color = self.COLOR_STOPPED

        # 원형 인디케이터를 스타일시트로 표시 (간단한 방법)
        self.indicator.setStyleSheet(f"""
            QLabel {{
                background-color: rgb({color.red()}, {color.green()}, {color.blue()});
                border-radius: 8px;
                border: 1px solid rgb(100, 100, 100);
            }}
        """)

    def set_running(self, text: str = "실행 중"):
        """실행 중 상태로 설정"""
        self.set_state(StatusState.RUNNING, text)

    def set_stopped(self, text: str = "중지됨"):
        """중지됨 상태로 설정"""
        self.set_state(StatusState.STOPPED, text)

    def set_error(self, text: str = "에러"):
        """에러 상태로 설정"""
        self.set_state(StatusState.ERROR, text)

    def set_warning(self, text: str = "경고"):
        """경고 상태로 설정"""
        self.set_state(StatusState.WARNING, text)


class StatusBar(QWidget):
    """상태 바 위젯 (여러 StatusIndicator를 담는 컨테이너)"""

    def __init__(self, parent=None):
        """
        상태 바 초기화

        Args:
            parent: 부모 위젯
        """
        super().__init__(parent)

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 2, 5, 2)

        # Docker 상태
        self.docker_indicator = StatusIndicator("Docker:")
        layout.addWidget(self.docker_indicator)

        # Label Studio 상태
        self.labelstudio_indicator = StatusIndicator("Label Studio:")
        layout.addWidget(self.labelstudio_indicator)

        layout.addStretch()

        # 에러/경고 카운트
        self.error_count_label = QLabel("에러: 0개")
        layout.addWidget(self.error_count_label)

        self.warning_count_label = QLabel("경고: 0개")
        layout.addWidget(self.warning_count_label)

        # 마지막 업데이트 시간
        self.last_update_label = QLabel("업데이트: 방금")
        layout.addWidget(self.last_update_label)

        self.setLayout(layout)

        # 배경색 설정
        self.setStyleSheet("""
            StatusBar {
                background-color: rgb(40, 40, 40);
                border-top: 1px solid rgb(60, 60, 60);
            }
        """)

    def update_docker_status(self, state: StatusState, text: str = ""):
        """Docker 상태 업데이트"""
        self.docker_indicator.set_state(state, text)

    def update_labelstudio_status(self, state: StatusState, text: str = ""):
        """Label Studio 상태 업데이트"""
        self.labelstudio_indicator.set_state(state, text)

    def update_error_count(self, count: int):
        """에러 개수 업데이트"""
        self.error_count_label.setText(f"에러: {count}개")

    def update_warning_count(self, count: int):
        """경고 개수 업데이트"""
        self.warning_count_label.setText(f"경고: {count}개")

    def update_last_update(self, text: str):
        """마지막 업데이트 시간 업데이트"""
        self.last_update_label.setText(f"업데이트: {text}")
