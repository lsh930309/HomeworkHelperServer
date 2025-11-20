#!/usr/bin/env python3
"""
서버 제어 탭
Label Studio Docker 컨테이너 시작/중지 및 로그 모니터링
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox
)
from PyQt6.QtCore import QTimer
from pathlib import Path

from ..core.docker_manager import DockerManager, DockerStatus, LabelStudioStatus
from ..widgets.log_viewer import LogViewer
from ..widgets.status_indicator import StatusState


class ServerControlTab(QWidget):
    """서버 제어 탭"""

    def __init__(self, docker_manager: DockerManager, parent=None):
        """
        서버 제어 탭 초기화

        Args:
            docker_manager: Docker 관리자
            parent: 부모 위젯
        """
        super().__init__(parent)

        self.docker_manager = docker_manager
        self.log_viewer = None
        self.status_timer = None

        self.init_ui()
        self.start_status_monitoring()

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout()

        # 상태 표시 그룹
        status_group = QGroupBox("서버 상태")
        status_layout = QVBoxLayout()

        # Docker 상태
        docker_status_layout = QHBoxLayout()
        self.docker_status_label = QLabel("Docker: 확인 중...")
        docker_status_layout.addWidget(self.docker_status_label)
        docker_status_layout.addStretch()
        status_layout.addLayout(docker_status_layout)

        # Label Studio 상태
        ls_status_layout = QHBoxLayout()
        self.ls_status_label = QLabel("Label Studio: 확인 중...")
        ls_status_layout.addWidget(self.ls_status_label)
        ls_status_layout.addStretch()
        status_layout.addLayout(ls_status_layout)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # 제어 버튼 그룹
        control_group = QGroupBox("서버 제어")
        control_layout = QHBoxLayout()

        # 서버 시작 버튼
        self.start_button = QPushButton("🚀 서버 시작")
        self.start_button.setMinimumHeight(50)
        self.start_button.clicked.connect(self.start_server)
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: rgb(100, 200, 100);
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgb(120, 220, 120);
            }
        """)
        control_layout.addWidget(self.start_button)

        # 서버 중지 버튼
        self.stop_button = QPushButton("⏹ 서버 중지")
        self.stop_button.setMinimumHeight(50)
        self.stop_button.clicked.connect(self.stop_server)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: rgb(200, 100, 100);
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgb(220, 120, 120);
            }
        """)
        control_layout.addWidget(self.stop_button)

        # 브라우저 열기 버튼
        self.browser_button = QPushButton("🌐 브라우저 열기")
        self.browser_button.setMinimumHeight(50)
        self.browser_button.clicked.connect(self.open_browser)
        self.browser_button.setEnabled(False)
        self.browser_button.setStyleSheet("""
            QPushButton {
                background-color: rgb(100, 150, 200);
                font-size: 14pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgb(120, 170, 220);
            }
        """)
        control_layout.addWidget(self.browser_button)

        control_group.setLayout(control_layout)
        layout.addWidget(control_group)

        # 로그 뷰어
        log_group = QGroupBox("로그")
        log_layout = QVBoxLayout()

        self.log_viewer = LogViewer(max_lines=500)
        log_layout.addWidget(self.log_viewer)

        # 로그 새로고침 버튼
        refresh_button = QPushButton("로그 새로고침")
        refresh_button.clicked.connect(self.refresh_logs)
        log_layout.addWidget(refresh_button)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        self.setLayout(layout)

    def start_status_monitoring(self):
        """상태 모니터링 시작 (2초마다)"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(2000)  # 2초

        # 즉시 한번 실행
        self.update_status()

    def update_status(self):
        """상태 업데이트"""
        # Docker 상태 확인
        docker_status = self.docker_manager.get_docker_status()

        if docker_status == DockerStatus.NOT_INSTALLED:
            self.docker_status_label.setText("❌ Docker: 설치되지 않음")
            self.docker_status_label.setStyleSheet("color: rgb(255, 100, 100);")
            self.start_button.setEnabled(False)
        elif docker_status == DockerStatus.NOT_RUNNING:
            self.docker_status_label.setText("⚠️ Docker: 실행되지 않음")
            self.docker_status_label.setStyleSheet("color: rgb(255, 200, 100);")
            self.start_button.setEnabled(False)
        else:
            self.docker_status_label.setText("✅ Docker: 실행 중")
            self.docker_status_label.setStyleSheet("color: rgb(100, 200, 100);")
            self.start_button.setEnabled(True)

        # Label Studio 상태 확인
        ls_status = self.docker_manager.get_label_studio_status()

        if ls_status == LabelStudioStatus.STOPPED:
            self.ls_status_label.setText("⭕ Label Studio: 중지됨")
            self.ls_status_label.setStyleSheet("color: rgb(150, 150, 150);")
            self.stop_button.setEnabled(False)
            self.browser_button.setEnabled(False)
            if docker_status == DockerStatus.RUNNING:
                self.start_button.setEnabled(True)
        elif ls_status == LabelStudioStatus.STARTING:
            self.ls_status_label.setText("⏳ Label Studio: 시작 중...")
            self.ls_status_label.setStyleSheet("color: rgb(255, 200, 100);")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.browser_button.setEnabled(False)
        elif ls_status == LabelStudioStatus.RUNNING:
            self.ls_status_label.setText("✅ Label Studio: 실행 중")
            self.ls_status_label.setStyleSheet("color: rgb(100, 200, 100);")
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.browser_button.setEnabled(True)
        else:
            self.ls_status_label.setText("❌ Label Studio: 에러")
            self.ls_status_label.setStyleSheet("color: rgb(255, 100, 100);")
            self.stop_button.setEnabled(True)
            self.browser_button.setEnabled(False)

    def start_server(self):
        """서버 시작"""
        self.log_viewer.add_log("Label Studio 서버 시작 중...", "INFO")
        self.start_button.setEnabled(False)

        success, message = self.docker_manager.start_label_studio()

        if success:
            self.log_viewer.add_log(message, "INFO")
        else:
            self.log_viewer.add_log(message, "ERROR")
            self.start_button.setEnabled(True)

        # 상태 즉시 업데이트
        self.update_status()

        # 로그 새로고침
        self.refresh_logs()

    def stop_server(self):
        """서버 중지"""
        self.log_viewer.add_log("Label Studio 서버 중지 중...", "INFO")
        self.stop_button.setEnabled(False)

        success, message = self.docker_manager.stop_label_studio()

        if success:
            self.log_viewer.add_log(message, "INFO")
        else:
            self.log_viewer.add_log(message, "ERROR")
            self.stop_button.setEnabled(True)

        # 상태 즉시 업데이트
        self.update_status()

    def open_browser(self):
        """브라우저 열기"""
        if self.docker_manager.open_browser():
            self.log_viewer.add_log("브라우저 열기 성공", "INFO")
        else:
            self.log_viewer.add_log("브라우저 열기 실패", "ERROR")

    def refresh_logs(self):
        """로그 새로고침"""
        logs = self.docker_manager.get_logs(lines=100)
        self.log_viewer.add_log_lines(logs)

    def cleanup(self):
        """정리 작업"""
        if self.status_timer:
            self.status_timer.stop()
