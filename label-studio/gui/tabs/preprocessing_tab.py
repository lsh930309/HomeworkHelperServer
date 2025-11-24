#!/usr/bin/env python3
"""
전처리 탭
비디오 세그멘테이션 (SSIM 기반 안정 구간 분할)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QLineEdit, QFileDialog, QSlider, QComboBox,
    QCheckBox, QDoubleSpinBox, QSpinBox, QFormLayout
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
        self.preset_combo.addItems(["빠른", "표준", "정밀", "사용자 정의"])
        self.preset_combo.setCurrentIndex(1)  # 기본: 표준
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        sampling_layout.addLayout(preset_layout)

        # 사용자 정의 파라미터 그룹 (처음에는 숨김)
        self.custom_params_group = QGroupBox("사용자 정의 파라미터")
        custom_params_layout = QFormLayout()

        # scene_threshold
        self.scene_threshold_spin = QDoubleSpinBox()
        self.scene_threshold_spin.setRange(0.0, 1.0)
        self.scene_threshold_spin.setSingleStep(0.05)
        self.scene_threshold_spin.setValue(0.3)
        self.scene_threshold_spin.setDecimals(2)
        custom_params_layout.addRow("장면 전환 임계값:", self.scene_threshold_spin)

        # static_threshold
        self.static_threshold_spin = QDoubleSpinBox()
        self.static_threshold_spin.setRange(0.0, 1.0)
        self.static_threshold_spin.setSingleStep(0.05)
        self.static_threshold_spin.setValue(0.95)
        self.static_threshold_spin.setDecimals(2)
        custom_params_layout.addRow("정적 구간 임계값:", self.static_threshold_spin)

        # min_duration
        self.min_duration_spin = QDoubleSpinBox()
        self.min_duration_spin.setRange(1.0, 60.0)
        self.min_duration_spin.setSingleStep(1.0)
        self.min_duration_spin.setValue(5.0)
        self.min_duration_spin.setSuffix(" 초")
        custom_params_layout.addRow("최소 길이:", self.min_duration_spin)

        # max_duration
        self.max_duration_spin = QDoubleSpinBox()
        self.max_duration_spin.setRange(10.0, 300.0)
        self.max_duration_spin.setSingleStep(5.0)
        self.max_duration_spin.setValue(60.0)
        self.max_duration_spin.setSuffix(" 초")
        custom_params_layout.addRow("최대 길이:", self.max_duration_spin)

        # ssim_scale
        self.ssim_scale_spin = QDoubleSpinBox()
        self.ssim_scale_spin.setRange(0.1, 1.0)
        self.ssim_scale_spin.setSingleStep(0.05)
        self.ssim_scale_spin.setValue(0.25)
        self.ssim_scale_spin.setDecimals(2)
        custom_params_layout.addRow("SSIM 해상도 스케일:", self.ssim_scale_spin)

        # frame_skip
        self.frame_skip_spin = QSpinBox()
        self.frame_skip_spin.setRange(1, 10)
        self.frame_skip_spin.setValue(1)
        custom_params_layout.addRow("프레임 스킵:", self.frame_skip_spin)

        self.custom_params_group.setLayout(custom_params_layout)
        self.custom_params_group.setVisible(False)  # 기본적으로 숨김
        sampling_layout.addWidget(self.custom_params_group)

        # GPU 가속 옵션
        self.use_gpu_checkbox = QCheckBox("GPU 가속 사용 (CUDA 사용 가능 시)")
        self.use_gpu_checkbox.setChecked(False)  # 기본: 비활성화
        self.use_gpu_checkbox.setToolTip("CUDA가 설치된 GPU를 사용하여 SSIM 계산을 가속합니다. PyTorch가 필요합니다.")
        self.use_gpu_checkbox.stateChanged.connect(self.on_gpu_checkbox_changed)
        sampling_layout.addWidget(self.use_gpu_checkbox)

        # 실험 기능: 채택되지 않은 구간 저장
        self.save_discarded_checkbox = QCheckBox("채택되지 않은 구간도 저장 (실험 기능)")
        self.save_discarded_checkbox.setToolTip("원본에서 세그먼트로 채택되지 않은 나머지 구간을 else 폴더에 저장합니다.")
        sampling_layout.addWidget(self.save_discarded_checkbox)

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

    def _on_preset_changed(self, index):
        """프리셋 변경 시 사용자 정의 파라미터 표시/숨김"""
        preset_name = self.preset_combo.currentText()
        if preset_name == "사용자 정의":
            self.custom_params_group.setVisible(True)
        else:
            self.custom_params_group.setVisible(False)

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

        preset_name = self.preset_combo.currentText()

        # 프리셋에 따른 파라미터
        if preset_name == "사용자 정의":
            # 사용자 정의 파라미터 사용
            params = {
                "scene_threshold": self.scene_threshold_spin.value(),
                "static_threshold": self.static_threshold_spin.value(),
                "min_duration": self.min_duration_spin.value(),
                "max_duration": self.max_duration_spin.value(),
                "ssim_scale": self.ssim_scale_spin.value(),
                "frame_skip": self.frame_skip_spin.value()
            }
        else:
            # 프리셋 파라미터
            preset_map = {
                "빠른": {
                    "scene_threshold": 0.3,
                    "static_threshold": 0.95,
                    "min_duration": 5.0,
                    "max_duration": 60.0,
                    "ssim_scale": 0.25,
                    "frame_skip": 3
                },
                "표준": {
                    "scene_threshold": 0.3,
                    "static_threshold": 0.95,
                    "min_duration": 5.0,
                    "max_duration": 60.0,
                    "ssim_scale": 0.25,
                    "frame_skip": 1
                },
                "정밀": {
                    "scene_threshold": 0.3,
                    "static_threshold": 0.97,
                    "min_duration": 10.0,
                    "max_duration": 60.0,
                    "ssim_scale": 1.0,
                    "frame_skip": 1
                }
            }
            params = preset_map[preset_name]

        # 공통 파라미터
        params["save_discarded"] = self.save_discarded_checkbox.isChecked()
        params["use_gpu"] = self.use_gpu_checkbox.isChecked()

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

        # 초기에는 불확정 모드로 시작 (전체 프레임 수를 아직 모름)
        self.progress_widget.set_indeterminate("비디오 분석 중...")

        # 시작 로그 출력
        self.log_viewer.add_log("=" * 60, "INFO")
        self.log_viewer.add_log("비디오 세그멘테이션 시작", "INFO")
        self.log_viewer.add_log(f"프리셋: {self.preset_combo.currentText()}", "INFO")
        self.log_viewer.add_log("=" * 60, "INFO")

        self.worker.start()

    def _on_progress(self, current, total):
        """진행 상황 업데이트"""
        # 첫 번째 진행 업데이트에서 전체 프레임 수를 설정
        if self.progress_widget.total_items != total:
            self.progress_widget.start_progress(total, "비디오 세그멘테이션")

        self.progress_widget.update_progress(current, f"프레임 처리 중... {current:,}/{total:,}")

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

    def _verify_gpu_acceleration(self) -> bool:
        """
        GPU 가속 기능 검증 (실제 텐서 생성 및 연산 테스트)

        Returns:
            bool: GPU 가속이 정상 작동하면 True
        """
        try:
            import torch

            # CUDA 사용 가능 여부 확인
            if not torch.cuda.is_available():
                self.log_viewer.add_log("❌ CUDA를 사용할 수 없습니다.", "ERROR")
                return False

            # GPU 디바이스 생성
            device = torch.device('cuda')
            gpu_name = torch.cuda.get_device_name(0)
            self.log_viewer.add_log(f"   GPU 감지: {gpu_name}", "INFO")

            # 실제 GPU 텐서 생성 및 연산 테스트
            test_tensor = torch.randn(100, 100, device=device)
            result = test_tensor @ test_tensor.T
            torch.cuda.synchronize()

            # 메모리 정보 확인
            memory_allocated = torch.cuda.memory_allocated(0) / 1024 / 1024  # MB
            memory_reserved = torch.cuda.memory_reserved(0) / 1024 / 1024    # MB

            self.log_viewer.add_log(f"   GPU 메모리 할당: {memory_allocated:.1f} MB", "INFO")
            self.log_viewer.add_log(f"   GPU 메모리 예약: {memory_reserved:.1f} MB", "INFO")

            return True

        except ImportError:
            self.log_viewer.add_log("❌ PyTorch를 import할 수 없습니다.", "ERROR")
            return False
        except RuntimeError as e:
            self.log_viewer.add_log(f"❌ GPU 텐서 생성 실패: {e}", "ERROR")
            return False
        except Exception as e:
            self.log_viewer.add_log(f"❌ GPU 검증 실패: {e}", "ERROR")
            return False

    def on_gpu_checkbox_changed(self, state):
        """GPU 가속 체크박스 상태 변경 시"""
        from PyQt6.QtWidgets import QMessageBox

        if state == Qt.CheckState.Checked.value:
            # GPU 가속 활성화 시도
            try:
                # PyTorch 설치 확인
                sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
                from utils.pytorch_installer import PyTorchInstaller

                installer = PyTorchInstaller.get_instance()

                # 이미 설치되어 있는 경우
                if installer.is_pytorch_installed():
                    installer.add_to_path()
                    self.log_viewer.add_log("✅ PyTorch 감지됨, GPU 가속 활성화", "INFO")

                    # 즉시 GPU 검증 수행
                    self.log_viewer.add_log("🔍 GPU 가속 기능 검증 중...", "INFO")
                    if self._verify_gpu_acceleration():
                        self.log_viewer.add_log("✅ GPU 가속 검증 완료! 정상 작동합니다.", "INFO")
                    else:
                        self.log_viewer.add_log("⚠️ GPU 검증 실패, CPU 모드로 전환합니다.", "WARNING")
                        self.use_gpu_checkbox.setChecked(False)
                    return

                # 미설치 시 CUDA 버전 감지
                cuda_version = installer.detect_cuda_version()

                if cuda_version is None:
                    # CUDA 감지 실패
                    QMessageBox.warning(
                        self,
                        "CUDA 감지 실패",
                        "NVIDIA GPU 또는 드라이버를 감지할 수 없습니다.\n\n"
                        "다음을 확인해주세요:\n"
                        "1. NVIDIA GPU가 설치되어 있나요?\n"
                        "2. NVIDIA 드라이버가 설치되어 있나요?\n"
                        "3. nvidia-smi 명령어가 작동하나요?\n\n"
                        "드라이버 다운로드:\n"
                        "https://www.nvidia.com/Download/index.aspx"
                    )
                    self.use_gpu_checkbox.setChecked(False)
                    return

                # 설치 가이드 다이얼로그 표시
                from ..dialogs.pytorch_install_dialog import PyTorchInstallDialog
                dialog = PyTorchInstallDialog(self, cuda_version)
                result = dialog.exec()

                if result == QMessageBox.DialogCode.Accepted and dialog.was_successful():
                    self.log_viewer.add_log("✅ PyTorch 설치 완료, GPU 가속 활성화", "INFO")

                    # 즉시 GPU 검증 수행
                    self.log_viewer.add_log("🔍 GPU 가속 기능 검증 중...", "INFO")
                    if self._verify_gpu_acceleration():
                        self.log_viewer.add_log("✅ GPU 가속 검증 완료! 정상 작동합니다.", "INFO")
                    else:
                        self.log_viewer.add_log("⚠️ GPU 검증 실패, CPU 모드로 전환합니다.", "WARNING")
                        self.use_gpu_checkbox.setChecked(False)
                else:
                    self.log_viewer.add_log("⚠️ PyTorch 설치 취소", "WARNING")
                    self.use_gpu_checkbox.setChecked(False)

            except Exception as e:
                self.log_viewer.add_log(f"❌ GPU 가속 초기화 실패: {e}", "ERROR")
                QMessageBox.critical(
                    self,
                    "오류",
                    f"GPU 가속 초기화 중 오류가 발생했습니다:\n\n{e}"
                )
                self.use_gpu_checkbox.setChecked(False)
        else:
            # GPU 가속 비활성화
            self.log_viewer.add_log("GPU 가속 비활성화, CPU 모드로 전환", "INFO")
