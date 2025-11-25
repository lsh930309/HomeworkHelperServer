#!/usr/bin/env python3
"""
전처리 탭
비디오 세그멘테이션 (Optical Flow 기반 동적 구간 분할)
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

        # 앱 시작 시 기존 PyTorch 자동 감지
        self._auto_detect_pytorch()

    def _auto_detect_pytorch(self):
        """앱 시작 시 기존 PyTorch 자동 감지 및 GPU 체크박스 상태 업데이트"""
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))
            from utils.pytorch_installer import PyTorchInstaller

            installer = PyTorchInstaller.get_instance()

            if installer.is_pytorch_installed():
                version_info = installer.get_installed_version()
                pytorch_version = version_info.get("pytorch", "unknown") if version_info else "unknown"

                # PyTorch 경로를 sys.path에 추가
                installer.add_to_path()

                # GPU 체크박스를 자동으로 활성화 (단, 체크는 하지 않음 - 사용자가 선택하도록)
                self.log_viewer.add_log(f"✅ 기존 PyTorch {pytorch_version} 감지됨", "INFO")
                self.log_viewer.add_log(f"   설치 위치: {installer.install_dir}", "INFO")
                self.log_viewer.add_log(f"   💡 'GPU 가속 사용' 체크박스를 활성화하여 사용할 수 있습니다.", "INFO")

                # GPU 체크박스 활성화 (선택은 사용자가)
                self.gpu_checkbox.setEnabled(True)
            else:
                self.log_viewer.add_log("⚠️ PyTorch가 설치되지 않았습니다.", "WARNING")
                self.log_viewer.add_log("   'GPU 가속 사용' 체크박스를 클릭하여 설치할 수 있습니다.", "INFO")
        except Exception as e:
            # 감지 실패 시 무시 (기존 동작 유지)
            pass

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

        # motion_threshold
        self.motion_threshold_spin = QDoubleSpinBox()
        self.motion_threshold_spin.setRange(0.5, 10.0)
        self.motion_threshold_spin.setSingleStep(0.5)
        self.motion_threshold_spin.setValue(2.0)
        self.motion_threshold_spin.setDecimals(1)
        self.motion_threshold_spin.setToolTip("이보다 낮은 움직임은 정적 구간으로 판단 (제거됨)")
        custom_params_layout.addRow("정적 구간 임계값:", self.motion_threshold_spin)

        # target_duration
        self.target_duration_spin = QDoubleSpinBox()
        self.target_duration_spin.setRange(10.0, 300.0)
        self.target_duration_spin.setSingleStep(5.0)
        self.target_duration_spin.setValue(30.0)
        self.target_duration_spin.setSuffix(" 초")
        self.target_duration_spin.setToolTip("최종 클립 길이 (동적 구간 병합 후 분할)")
        custom_params_layout.addRow("목표 클립 길이:", self.target_duration_spin)

        # min_dynamic_duration
        self.min_dynamic_duration_spin = QDoubleSpinBox()
        self.min_dynamic_duration_spin.setRange(1.0, 30.0)
        self.min_dynamic_duration_spin.setSingleStep(0.5)
        self.min_dynamic_duration_spin.setValue(3.0)
        self.min_dynamic_duration_spin.setSuffix(" 초")
        self.min_dynamic_duration_spin.setToolTip("최소 동적 구간 길이 (이보다 짧으면 무시)")
        custom_params_layout.addRow("최소 동적 구간:", self.min_dynamic_duration_spin)

        # batch_size
        self.batch_size_spin = QSpinBox()
        self.batch_size_spin.setRange(8, 128)
        self.batch_size_spin.setSingleStep(8)
        self.batch_size_spin.setValue(32)
        self.batch_size_spin.setToolTip("GPU 배치 크기 (VRAM에 따라 자동 조정됨)")
        custom_params_layout.addRow("배치 크기:", self.batch_size_spin)

        # flow_scale
        self.flow_scale_spin = QDoubleSpinBox()
        self.flow_scale_spin.setRange(0.1, 1.0)
        self.flow_scale_spin.setSingleStep(0.1)
        self.flow_scale_spin.setValue(0.5)
        self.flow_scale_spin.setDecimals(1)
        self.flow_scale_spin.setToolTip("Optical Flow 계산 해상도 (낮을수록 빠름)")
        custom_params_layout.addRow("Flow 해상도 스케일:", self.flow_scale_spin)

        # frame_skip
        self.frame_skip_spin = QSpinBox()
        self.frame_skip_spin.setRange(1, 10)
        self.frame_skip_spin.setValue(1)
        custom_params_layout.addRow("프레임 스킵:", self.frame_skip_spin)

        self.custom_params_group.setLayout(custom_params_layout)
        self.custom_params_group.setVisible(False)  # 기본적으로 숨김
        sampling_layout.addWidget(self.custom_params_group)

        # GPU 가속 옵션
        self.gpu_checkbox = QCheckBox("GPU 가속 사용 (CUDA 사용 가능 시)")
        self.gpu_checkbox.setChecked(False)  # 기본: 비활성화
        self.gpu_checkbox.setToolTip("CUDA가 설치된 GPU를 사용하여 Optical Flow 계산을 가속합니다. PyTorch가 필요합니다.")
        self.gpu_checkbox.stateChanged.connect(self.on_gpu_checkbox_changed)
        sampling_layout.addWidget(self.gpu_checkbox)

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
        use_gpu = self.gpu_checkbox.isChecked()

        # 프리셋에 따른 파라미터
        if preset_name == "사용자 정의":
            # 사용자 정의 모드: 사용자가 입력한 값 그대로 사용 (의도적인 제한 허용)
            params = {
                "motion_threshold": self.motion_threshold_spin.value(),
                "target_duration": self.target_duration_spin.value(),
                "min_dynamic_duration": self.min_dynamic_duration_spin.value(),
                "batch_size": self.batch_size_spin.value(),
                "flow_scale": self.flow_scale_spin.value(),
                "frame_skip": self.frame_skip_spin.value()
            }
        else:
            # 프리셋 파라미터
            # GPU 사용 시: batch_size를 128(백엔드 MAX)로 설정하여 
            # 백엔드의 _determine_batch_size가 VRAM에 맞춰 자동으로 깎도록 유도 (Auto Mode)
            auto_batch_size = 128 if use_gpu else 32

            preset_map = {
                "빠른": {
                    "motion_threshold": 2.0,
                    "target_duration": 30.0,
                    "min_dynamic_duration": 3.0,
                    "batch_size": auto_batch_size, # 여기가 핵심! GPU면 128, 아니면 32
                    "flow_scale": 0.5,
                    "frame_skip": 3
                },
                "표준": {
                    "motion_threshold": 2.0,
                    "target_duration": 30.0,
                    "min_dynamic_duration": 3.0,
                    "batch_size": auto_batch_size, # 핵심!
                    "flow_scale": 0.5,
                    "frame_skip": 2
                },
                "정밀": {
                    "motion_threshold": 1.0,
                    "target_duration": 30.0,
                    "min_dynamic_duration": 3.0,
                    "batch_size": auto_batch_size, # 핵심!
                    "flow_scale": 0.5,
                    "frame_skip": 1
                }
            }
            params = preset_map[preset_name]

        # 공통 파라미터 추가
        params["use_gpu"] = use_gpu

        # (로그 출력 부분: 사용자에게 알림)
        if use_gpu and preset_name != "사용자 정의":
             self.log_viewer.add_log(f"💡 GPU 자동 최적화: 배치 크기를 최대({params['batch_size']})로 설정합니다.", "INFO")

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

        # 초기에는 불확정 모드로 시작
        self.progress_widget.set_indeterminate("비디오 분석 중...")

        # 시작 로그 출력
        self.log_viewer.add_log("=" * 60, "INFO")
        self.log_viewer.add_log("비디오 세그멘테이션 시작", "INFO")
        self.log_viewer.add_log(f"프리셋: {preset_name}", "INFO")
        if use_gpu:
             self.log_viewer.add_log(f"가속 모드: GPU (CUDA)", "INFO")
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
                    version_info = installer.get_installed_version()
                    pytorch_version = version_info.get("pytorch", "unknown") if version_info else "unknown"
                    self.log_viewer.add_log(f"✅ PyTorch {pytorch_version} 감지됨, GPU 가속 활성화", "INFO")

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
