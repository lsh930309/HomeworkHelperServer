#!/usr/bin/env python3
"""
전처리 탭
비디오 세그멘테이션 (SSIM 기반 안정 구간 분할)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QLineEdit, QFileDialog, QSlider, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from pathlib import Path

from ..core.sampler_manager import SamplerManager
from ..core.config_manager import get_config_manager
from ..widgets.progress_widget import ProgressWidget


class SegmentationWorker(QThread):
    """세그멘테이션 작업 스레드"""
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, sampler_manager, input_path, output_path, params):
        super().__init__()
        self.sampler_manager = sampler_manager
        self.input_path = input_path
        self.output_path = output_path
        self.params = params

    def run(self):
        try:
            result = self.sampler_manager.segment_video(
                self.input_path,
                self.output_path,
                **self.params,
                progress_callback=lambda c, t: self.progress.emit(c, t)
            )
            self.finished.emit(result.success, result.message)
        except Exception as e:
            self.finished.emit(False, f"오류: {e}")


class PreprocessingTab(QWidget):
    """전처리 탭"""

    def __init__(self, parent=None):
        """전처리 탭 초기화"""
        super().__init__(parent)

        self.sampler_manager = SamplerManager()
        self.config_manager = get_config_manager()
        self.worker = None

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout()

        # 비디오 세그멘테이션 그룹
        sampling_group = QGroupBox("비디오 세그멘테이션")
        sampling_layout = QVBoxLayout()

        # 입력 비디오
        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("입력 비디오:"))
        self.input_video_edit = QLineEdit()
        self.input_video_edit.setPlaceholderText("비디오 파일 경로...")
        input_layout.addWidget(self.input_video_edit)
        browse_input_btn = QPushButton("찾아보기")
        browse_input_btn.clicked.connect(self.browse_input_video)
        input_layout.addWidget(browse_input_btn)
        sampling_layout.addLayout(input_layout)

        # 출력 디렉토리
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("출력 폴더:"))
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("출력 폴더 경로...")
        output_layout.addWidget(self.output_dir_edit)
        browse_output_btn = QPushButton("찾아보기")
        browse_output_btn.clicked.connect(self.browse_output_dir)
        output_layout.addWidget(browse_output_btn)
        sampling_layout.addLayout(output_layout)

        # 프리셋 선택
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("프리셋:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["빠른 세그멘테이션", "표준 세그멘테이션", "정밀 세그멘테이션"])
        self.preset_combo.setCurrentIndex(1)  # 기본: 표준
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        sampling_layout.addLayout(preset_layout)

        # 세그멘테이션 시작 버튼
        self.start_sampling_btn = QPushButton("🎬 세그멘테이션 시작")
        self.start_sampling_btn.setMinimumHeight(40)
        self.start_sampling_btn.clicked.connect(self.start_segmentation)
        sampling_layout.addWidget(self.start_sampling_btn)

        # 진행률 위젯
        self.progress_widget = ProgressWidget()
        self.progress_widget.cancel_requested.connect(self.cancel_segmentation)
        sampling_layout.addWidget(self.progress_widget)

        sampling_group.setLayout(sampling_layout)
        layout.addWidget(sampling_group)

        layout.addStretch()

        self.setLayout(layout)

    def browse_input_video(self):
        """입력 비디오 찾아보기"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "입력 비디오 선택",
            "",
            "Video Files (*.mp4 *.avi *.mov *.mkv)"
        )
        if file_path:
            self.input_video_edit.setText(file_path)

    def browse_output_dir(self):
        """출력 디렉토리 찾아보기"""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "출력 폴더 선택",
            ""
        )
        if dir_path:
            self.output_dir_edit.setText(dir_path)

    def start_segmentation(self):
        """세그멘테이션 시작"""
        input_path = Path(self.input_video_edit.text())
        output_path = Path(self.output_dir_edit.text())

        if not input_path.exists():
            self.progress_widget.finish_progress(False, "입력 비디오 파일이 없습니다.")
            return

        if not output_path.exists():
            output_path.mkdir(parents=True, exist_ok=True)

        # 프리셋에 따른 파라미터
        preset_map = {
            "빠른 세그멘테이션": {
                "scene_threshold": 0.3,
                "dynamic_low": 0.35,
                "dynamic_high": 0.85,
                "min_duration": 5.0,
                "max_duration": 60.0
            },
            "표준 세그멘테이션": {
                "scene_threshold": 0.3,
                "dynamic_low": 0.4,
                "dynamic_high": 0.8,
                "min_duration": 5.0,
                "max_duration": 60.0
            },
            "정밀 세그멘테이션": {
                "scene_threshold": 0.3,
                "dynamic_low": 0.45,
                "dynamic_high": 0.75,
                "min_duration": 10.0,
                "max_duration": 60.0
            }
        }

        params = preset_map[self.preset_combo.currentText()]

        # 작업 스레드 시작
        self.worker = SegmentationWorker(
            self.sampler_manager,
            input_path,
            output_path,
            params
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)

        self.start_sampling_btn.setEnabled(False)
        self.progress_widget.start_progress(100, "비디오 세그멘테이션")
        self.worker.start()

    def _on_progress(self, current, total):
        """진행 상황 업데이트"""
        self.progress_widget.update_progress(current, f"프레임 처리 중... {current}/{total}")

    def _on_finished(self, success, message):
        """세그멘테이션 완료"""
        self.progress_widget.finish_progress(success, message)
        self.start_sampling_btn.setEnabled(True)
        self.worker = None

    def cancel_segmentation(self):
        """세그멘테이션 취소"""
        if self.worker:
            self.worker.terminate()
            self.worker.wait()
            self.progress_widget.finish_progress(False, "사용자가 취소했습니다.")
            self.start_sampling_btn.setEnabled(True)
            self.worker = None
