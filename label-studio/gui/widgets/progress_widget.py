#!/usr/bin/env python3
"""
진행률 위젯
작업 진행 상황 표시 및 취소 기능
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QProgressBar, QLabel, QPushButton
)
from PyQt6.QtCore import Qt, pyqtSignal
from datetime import datetime, timedelta
from typing import Optional


class ProgressWidget(QWidget):
    """진행률 위젯"""

    # 시그널
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        """
        진행률 위젯 초기화

        Args:
            parent: 부모 위젯
        """
        super().__init__(parent)

        self.start_time: Optional[datetime] = None
        self.total_items = 0
        self.current_item = 0

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 프로그레스 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # 정보 레이블 및 취소 버튼
        info_layout = QHBoxLayout()

        self.status_label = QLabel("대기 중...")
        info_layout.addWidget(self.status_label)

        info_layout.addStretch()

        self.eta_label = QLabel("")
        info_layout.addWidget(self.eta_label)

        self.cancel_button = QPushButton("취소")
        self.cancel_button.clicked.connect(self.cancel_requested.emit)
        self.cancel_button.setEnabled(False)
        info_layout.addWidget(self.cancel_button)

        layout.addLayout(info_layout)

        self.setLayout(layout)

    def start_progress(self, total: int, task_name: str = "작업"):
        """
        진행 시작

        Args:
            total: 전체 항목 수
            task_name: 작업 이름
        """
        self.total_items = total
        self.current_item = 0
        self.start_time = datetime.now()

        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(0)

        self.status_label.setText(f"{task_name} 시작...")
        self.eta_label.setText("")
        self.cancel_button.setEnabled(True)

    def update_progress(self, current: int, message: str = ""):
        """
        진행 상황 업데이트

        Args:
            current: 현재 완료 항목 수
            message: 상태 메시지
        """
        self.current_item = current
        self.progress_bar.setValue(current)

        # 진행률 계산
        if self.total_items > 0:
            percentage = (current / self.total_items) * 100
            self.progress_bar.setFormat(f"{percentage:.1f}% ({current}/{self.total_items})")
        else:
            self.progress_bar.setFormat("0%")

        # 상태 메시지
        if message:
            self.status_label.setText(message)
        else:
            self.status_label.setText(f"진행 중... {current}/{self.total_items}")

        # 예상 남은 시간 계산
        if self.start_time and current > 0:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            items_per_second = current / elapsed
            remaining_items = self.total_items - current

            if items_per_second > 0:
                eta_seconds = remaining_items / items_per_second
                eta = timedelta(seconds=int(eta_seconds))
                self.eta_label.setText(f"남은 시간: {eta}")
            else:
                self.eta_label.setText("")
        else:
            self.eta_label.setText("")

    def finish_progress(self, success: bool = True, message: str = ""):
        """
        진행 완료

        Args:
            success: 성공 여부
            message: 완료 메시지
        """
        self.progress_bar.setValue(self.total_items)
        self.cancel_button.setEnabled(False)

        if success:
            if message:
                self.status_label.setText(message)
            else:
                self.status_label.setText("✅ 완료!")
            self.progress_bar.setFormat("100%")
        else:
            if message:
                self.status_label.setText(message)
            else:
                self.status_label.setText("❌ 실패")

        self.eta_label.setText("")

    def reset(self):
        """진행 상황 초기화"""
        self.progress_bar.setValue(0)
        self.status_label.setText("대기 중...")
        self.eta_label.setText("")
        self.cancel_button.setEnabled(False)
        self.start_time = None
        self.total_items = 0
        self.current_item = 0

    def set_indeterminate(self, message: str = "처리 중..."):
        """
        불확정 진행 모드 (전체 개수를 모를 때)

        Args:
            message: 상태 메시지
        """
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(0)  # 불확정 모드
        self.status_label.setText(message)
        self.eta_label.setText("")
        self.cancel_button.setEnabled(True)
