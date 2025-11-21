#!/usr/bin/env python3
"""
Label Studio Manager - 메인 윈도우
Label Studio 서버 제어 및 데이터 전처리를 위한 GUI 툴
"""

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QMessageBox
)
from PyQt6.QtCore import Qt, QTimer
from pathlib import Path

from .core.docker_manager import DockerManager
from .core.config_manager import get_config_manager
from .tabs import ServerControlTab, PreprocessingTab
from .widgets.status_indicator import StatusBar, StatusState


class LabelStudioManager(QMainWindow):
    """Label Studio Manager 메인 윈도우"""

    def __init__(self):
        """메인 윈도우 초기화"""
        super().__init__()

        # 매니저 초기화
        self.config_manager = get_config_manager()
        self.docker_manager = DockerManager()

        # UI 초기화
        self.init_ui()

        # 설정 로드
        self.load_settings()

        # 상태 바 자동 업데이트 타이머 시작
        self.start_status_monitoring()

    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("Label Studio Manager")

        # 설정된 윈도우 크기 사용
        config = self.config_manager.config
        self.resize(config.window_width, config.window_height)

        # 중앙 위젯
        central_widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 탭 위젯
        self.tab_widget = QTabWidget()

        # 서버 제어 탭
        self.server_tab = ServerControlTab(self.docker_manager)
        self.tab_widget.addTab(self.server_tab, "🖥 서버 제어")

        # 전처리 탭
        self.preprocessing_tab = PreprocessingTab()
        self.tab_widget.addTab(self.preprocessing_tab, "🎬 전처리")

        # TODO: 나머지 탭들 추가
        # self.schema_tab = SchemaManagerTab()
        # self.tab_widget.addTab(self.schema_tab, "📋 스키마 관리")

        # self.dataset_tab = DatasetTab()
        # self.tab_widget.addTab(self.dataset_tab, "📊 데이터셋")

        # self.settings_tab = SettingsTab()
        # self.tab_widget.addTab(self.settings_tab, "⚙ 설정")

        layout.addWidget(self.tab_widget)

        # 하단 상태 바
        self.status_bar_widget = StatusBar()
        layout.addWidget(self.status_bar_widget)

        central_widget.setLayout(layout)
        self.setCentralWidget(central_widget)

        # 다크 테마 적용
        self.apply_dark_theme()

        # 상태 바 초기 업데이트
        self.update_status_bar()

    def apply_dark_theme(self):
        """다크 테마 적용"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: rgb(45, 45, 45);
                color: rgb(220, 220, 220);
            }
            QTabWidget::pane {
                border: 1px solid rgb(60, 60, 60);
                background: rgb(45, 45, 45);
            }
            QTabBar::tab {
                background: rgb(60, 60, 60);
                color: rgb(220, 220, 220);
                padding: 10px 20px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: rgb(80, 80, 80);
            }
            QTabBar::tab:hover {
                background: rgb(70, 70, 70);
            }
            QGroupBox {
                border: 1px solid rgb(70, 70, 70);
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
                color: rgb(200, 200, 200);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QLabel {
                color: rgb(220, 220, 220);
            }
            QLineEdit {
                background-color: rgb(60, 60, 60);
                color: rgb(220, 220, 220);
                border: 1px solid rgb(80, 80, 80);
                padding: 5px;
                border-radius: 3px;
            }
            QPushButton {
                background-color: rgb(70, 70, 70);
                color: rgb(220, 220, 220);
                border: 1px solid rgb(90, 90, 90);
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: rgb(80, 80, 80);
            }
            QPushButton:pressed {
                background-color: rgb(60, 60, 60);
            }
            QPushButton:disabled {
                background-color: rgb(50, 50, 50);
                color: rgb(100, 100, 100);
            }
            QComboBox {
                background-color: rgb(60, 60, 60);
                color: rgb(220, 220, 220);
                border: 1px solid rgb(80, 80, 80);
                padding: 5px;
                border-radius: 3px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid rgb(220, 220, 220);
                margin-right: 5px;
            }
            QTextEdit {
                background-color: rgb(30, 30, 30);
                color: rgb(220, 220, 220);
                border: 1px solid rgb(60, 60, 60);
                border-radius: 3px;
            }
            QProgressBar {
                background-color: rgb(60, 60, 60);
                color: rgb(220, 220, 220);
                border: 1px solid rgb(80, 80, 80);
                border-radius: 3px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: rgb(100, 180, 100);
                border-radius: 3px;
            }
        """)

    def start_status_monitoring(self):
        """상태 모니터링 시작 (3초마다)"""
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_status_bar)
        self.status_timer.start(3000)  # 3초

        # 즉시 한 번 실행
        self.update_status_bar()

    def update_status_bar(self):
        """상태 바 업데이트"""
        # Docker 상태
        docker_status = self.docker_manager.get_docker_status()
        if docker_status.value == "running":
            self.status_bar_widget.update_docker_status(StatusState.RUNNING, "실행 중")
        elif docker_status.value == "not_running":
            self.status_bar_widget.update_docker_status(StatusState.WARNING, "미실행")
        else:
            self.status_bar_widget.update_docker_status(StatusState.ERROR, "미설치")

        # Label Studio 상태
        ls_status = self.docker_manager.get_label_studio_status()
        if ls_status.value == "running":
            self.status_bar_widget.update_labelstudio_status(StatusState.RUNNING, "실행 중")
        elif ls_status.value == "starting":
            self.status_bar_widget.update_labelstudio_status(StatusState.WARNING, "시작 중")
        elif ls_status.value == "error":
            self.status_bar_widget.update_labelstudio_status(StatusState.ERROR, "에러")
        else:
            self.status_bar_widget.update_labelstudio_status(StatusState.STOPPED, "중지됨")

        # 로그 에러/경고 카운트 (서버 탭에서 가져오기)
        if hasattr(self.server_tab, 'log_viewer'):
            error_count = self.server_tab.log_viewer.get_error_count()
            warning_count = self.server_tab.log_viewer.get_warning_count()
            self.status_bar_widget.update_error_count(error_count)
            self.status_bar_widget.update_warning_count(warning_count)

        self.status_bar_widget.update_last_update("방금")

    def load_settings(self):
        """설정 로드"""
        config = self.config_manager.config

        # 윈도우 크기 적용 (이미 init_ui에서 했음)
        pass

    def save_settings(self):
        """설정 저장"""
        # 윈도우 크기 저장
        self.config_manager.config.window_width = self.width()
        self.config_manager.config.window_height = self.height()
        self.config_manager.save()

    def closeEvent(self, event):
        """창 닫기 이벤트"""
        # 설정 저장
        self.save_settings()

        # 타이머 정리
        if hasattr(self, 'status_timer'):
            self.status_timer.stop()

        # 서버 탭 정리
        if hasattr(self.server_tab, 'cleanup'):
            self.server_tab.cleanup()

        event.accept()
