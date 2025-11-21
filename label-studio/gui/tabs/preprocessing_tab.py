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
import sys
from io import StringIO

from ..core.sampler_manager import SamplerManager
from ..core.config_manager import get_config_manager
from ..widgets.progress_widget import ProgressWidget
from ..widgets.log_viewer import LogViewer


class SegmentationWorker(QThread):
    """세그멘테이션 작업 스레드"""
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str)
    log_message = pyqtSignal(str, str)  # message, level

    def __init__(self, sampler_manager, input_path, output_path, params):
        super().__init__()
        self.sampler_manager = sampler_manager
        self.input_path = input_path
        self.output_path = output_path
        self.params = params

    def run(self):
        # stdout 캡처 설정
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            self.log_message.emit(f"세그멘테이션 시작: {self.input_path.name}", "INFO")
            self.log_message.emit(f"출력 경로: {self.output_path}", "INFO")

            result = self.sampler_manager.segment_video(
                self.input_path,
                self.output_path,
                **self.params,
                progress_callback=lambda c, t: self.progress.emit(c, t)
            )

            # 캡처된 출력 가져오기
            output = sys.stdout.getvalue()
            if output:
                # 줄 단위로 로그 전송
                for line in output.strip().split('\n'):
                    if line.strip():
                        # 로그 레벨 추정
                        if '❌' in line or '오류' in line or 'ERROR' in line:
                            level = "ERROR"
                        elif '⚠️' in line or '경고' in line or 'WARNING' in line:
                            level = "WARNING"
                        else:
                            level = "INFO"
                        self.log_message.emit(line, level)

            if result.success:
                self.log_message.emit(f"✅ {result.message}", "INFO")
            else:
                self.log_message.emit(f"❌ {result.message}", "ERROR")

            self.finished.emit(result.success, result.message)

        except Exception as e:
            error_msg = f"오류: {e}"
            self.log_message.emit(error_msg, "ERROR")
            self.finished.emit(False, error_msg)

        finally:
            # stdout 복원
            sys.stdout = old_stdout


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
        self.preset_combo.addItems(["빠른", "표준", "정밀"])
        self.preset_combo.setCurrentIndex(1)  # 기본: 표준
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        sampling_layout.addLayout(preset_layout)

        # 실험 기능: 채택되지 않은 구간 저장
        from PyQt6.QtWidgets import QCheckBox
        self.save_discarded_checkbox = QCheckBox("채택되지 않은 구간도 저장 (실험 기능)")
        self.save_discarded_checkbox.setToolTip("원본에서 세그먼트로 채택되지 않은 나머지 구간을 else 폴더에 저장합니다.")
        sampling_layout.addWidget(self.save_discarded_checkbox)

        # 멀티프로세싱 옵션
        self.multiprocessing_checkbox = QCheckBox("멀티프로세싱 사용 (8코어 기준 4-8배 빠름)")
        self.multiprocessing_checkbox.setChecked(True)  # 기본: 활성화
        self.multiprocessing_checkbox.setToolTip("CPU 멀티코어를 활용하여 병렬 처리합니다. 비활성화 시 싱글 프로세스로 실행됩니다.")
        sampling_layout.addWidget(self.multiprocessing_checkbox)

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

        # 로그 뷰어 그룹
        log_group = QGroupBox("처리 로그")
        log_layout = QVBoxLayout()

        self.log_viewer = LogViewer(max_lines=500)
        log_layout.addWidget(self.log_viewer)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

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
            # 출력 폴더 자동 설정: {원본파일명}_seg
            input_path = Path(file_path)
            output_path = input_path.parent / f"{input_path.stem}_seg"
            self.output_dir_edit.setText(str(output_path))

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
            "빠른": {
                "scene_threshold": 0.3,
                "dynamic_low": 0.35,
                "dynamic_high": 0.85,
                "min_duration": 5.0,
                "max_duration": 60.0,
                "ssim_scale": 0.25,
                "frame_skip": 3
            },
            "표준": {
                "scene_threshold": 0.3,
                "dynamic_low": 0.4,
                "dynamic_high": 0.8,
                "min_duration": 5.0,
                "max_duration": 60.0,
                "ssim_scale": 0.25,
                "frame_skip": 1
            },
            "정밀": {
                "scene_threshold": 0.3,
                "dynamic_low": 0.45,
                "dynamic_high": 0.75,
                "min_duration": 10.0,
                "max_duration": 60.0,
                "ssim_scale": 1.0,
                "frame_skip": 1
            }
        }

        params = preset_map[self.preset_combo.currentText()]
        params["save_discarded"] = self.save_discarded_checkbox.isChecked()
        params["use_multiprocessing"] = self.multiprocessing_checkbox.isChecked()

        # 작업 스레드 시작
        self.worker = SegmentationWorker(
            self.sampler_manager,
            input_path,
            output_path,
            params
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.log_message.connect(self._on_log_message)

        self.start_sampling_btn.setEnabled(False)
        self.progress_widget.start_progress(100, "비디오 세그멘테이션")

        # 시작 로그 출력
        self.log_viewer.add_log("=" * 60, "INFO")
        self.log_viewer.add_log("비디오 세그멘테이션 시작", "INFO")
        self.log_viewer.add_log(f"프리셋: {self.preset_combo.currentText()}", "INFO")
        self.log_viewer.add_log("=" * 60, "INFO")

        self.worker.start()

    def _on_progress(self, current, total):
        """진행 상황 업데이트"""
        self.progress_widget.update_progress(current, f"프레임 처리 중... {current}/{total}")

    def _on_log_message(self, message, level):
        """로그 메시지 처리"""
        self.log_viewer.add_log(message, level)

    def _on_finished(self, success, message):
        """세그멘테이션 완료"""
        self.progress_widget.finish_progress(success, message)
        self.start_sampling_btn.setEnabled(True)

        # 완료 로그
        self.log_viewer.add_log("=" * 60, "INFO")
        if success:
            self.log_viewer.add_log("✅ 세그멘테이션 완료!", "INFO")
        else:
            self.log_viewer.add_log("❌ 세그멘테이션 실패", "ERROR")
        self.log_viewer.add_log("=" * 60, "INFO")

        self.worker = None

    def cancel_segmentation(self):
        """세그멘테이션 취소"""
        if self.worker:
            self.log_viewer.add_log("사용자 취소 요청...", "WARNING")
            self.worker.terminate()
            self.worker.wait()
            self.progress_widget.finish_progress(False, "사용자가 취소했습니다.")
            self.log_viewer.add_log("❌ 작업이 취소되었습니다.", "WARNING")
            self.start_sampling_btn.setEnabled(True)
            self.worker = None
