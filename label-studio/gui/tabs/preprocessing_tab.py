#!/usr/bin/env python3
"""
전처리 탭
비디오 세그멘테이션 (SSIM 기반 안정 구간 분할)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QLineEdit, QFileDialog, QComboBox,
    QCheckBox, QDoubleSpinBox, QSpinBox, QFormLayout, QMessageBox
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
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            self.log_message.emit(f"세그멘테이션 시작: {self.input_path.name}", "INFO")
            self.log_message.emit(f"모드: {self.params.get('mode', 'unknown')}", "INFO")

            result = self.sampler_manager.segment_video(
                self.input_path,
                self.output_path,
                **self.params,
                progress_callback=lambda c, t: self.progress.emit(c, t)
            )

            output = sys.stdout.getvalue()
            if output:
                for line in output.strip().split('\n'):
                    if line.strip():
                        level = "INFO"
                        if '❌' in line or '오류' in line or 'ERROR' in line:
                            level = "ERROR"
                        elif '⚠️' in line or '경고' in line or 'WARNING' in line:
                            level = "WARNING"
                        self.log_message.emit(line, level)

            if result.success:
                self.log_message.emit(f"✅ {result.message}", "INFO")
            else:
                self.log_message.emit(f"❌ {result.message}", "ERROR")

            self.finished.emit(result.success, result.message)

        except Exception as e:
            error_msg = f"오류: {e}"
            self.log_message.emit(error_msg, "ERROR")
#!/usr/bin/env python3
"""
전처리 탭
비디오 세그멘테이션 (SSIM 기반 안정 구간 분할)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QGroupBox, QLineEdit, QFileDialog, QComboBox,
    QCheckBox, QDoubleSpinBox, QSpinBox, QFormLayout, QMessageBox
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
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            self.log_message.emit(f"세그멘테이션 시작: {self.input_path.name}", "INFO")
            self.log_message.emit(f"모드: {self.params.get('mode', 'unknown')}", "INFO")

            result = self.sampler_manager.segment_video(
                self.input_path,
                self.output_path,
                **self.params,
                progress_callback=lambda c, t: self.progress.emit(c, t)
            )

            output = sys.stdout.getvalue()
            if output:
                for line in output.strip().split('\n'):
                    if line.strip():
                        level = "INFO"
                        if '❌' in line or '오류' in line or 'ERROR' in line:
                            level = "ERROR"
                        elif '⚠️' in line or '경고' in line or 'WARNING' in line:
                            level = "WARNING"
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
            sys.stdout = old_stdout


class PreprocessingTab(QWidget):
    """전처리 탭"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.sampler_manager = SamplerManager()
        self.config_manager = get_config_manager()
        self.worker = None
        self.init_ui()
        
        # 앱 시작 시 기존 PyTorch 자동 감지 (복원됨)
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
            # 감지 실패 시 무시
            pass

    def init_ui(self):
        layout = QVBoxLayout()

        # 1. 비디오 세그멘테이션 그룹
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

        # 2. 모드 선택 (Auto vs Custom)
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("동작 모드:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["자동 설정 (Auto - 권장)", "사용자 정의 (Custom)"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        sampling_layout.addLayout(mode_layout)

        # 3. 상세 파라미터 (Custom 모드에서만 보임)
        self.custom_params_group = QGroupBox("상세 파라미터 설정")
        custom_params_layout = QFormLayout()

        # static_threshold
        self.static_threshold_spin = QDoubleSpinBox()
        self.static_threshold_spin.setRange(0.0, 1.0)
        self.static_threshold_spin.setSingleStep(0.01)
        self.static_threshold_spin.setValue(0.95)
        self.static_threshold_spin.setToolTip("SSIM 점수가 이보다 높으면 '정적(멈춘 화면)'으로 간주합니다.")
        custom_params_layout.addRow("정적 구간 임계값 (Static Threshold):", self.static_threshold_spin)

        # min_static_duration
        self.min_static_duration_spin = QDoubleSpinBox()
        self.min_static_duration_spin.setRange(0.1, 10.0)
        self.min_static_duration_spin.setSingleStep(0.1)
        self.min_static_duration_spin.setValue(1.0)
        self.min_static_duration_spin.setSuffix(" 초")
        self.min_static_duration_spin.setToolTip("이 시간보다 짧은 정적 구간은 무시하고 이어 붙입니다.")
        custom_params_layout.addRow("최소 정적 유지 시간:", self.min_static_duration_spin)

        # target_segment_duration
        self.target_duration_spin = QDoubleSpinBox()
        self.target_duration_spin.setRange(10.0, 60.0)
        self.target_duration_spin.setSingleStep(1.0)
        self.target_duration_spin.setValue(30.0)
        self.target_duration_spin.setSuffix(" 초")
        self.target_duration_spin.setToolTip("생성될 세그먼트 하나의 목표 길이입니다.")
        custom_params_layout.addRow("목표 세그먼트 길이:", self.target_duration_spin)

        # ssim_scale
        self.ssim_scale_spin = QDoubleSpinBox()
        self.ssim_scale_spin.setRange(0.1, 1.0)
        self.ssim_scale_spin.setSingleStep(0.05)
        self.ssim_scale_spin.setValue(1.0)
        self.ssim_scale_spin.setToolTip("SSIM 계산 시 해상도 비율입니다 (1.0=원본).")
        custom_params_layout.addRow("SSIM 해상도 스케일:", self.ssim_scale_spin)

        # frame_skip
        self.frame_skip_spin = QSpinBox()
        self.frame_skip_spin.setRange(1, 5)
        self.frame_skip_spin.setValue(1)
        self.frame_skip_spin.setToolTip("SSIM 계산 시 건너뛸 프레임 수입니다.")
        custom_params_layout.addRow("프레임 스킵:", self.frame_skip_spin)
        
        # Keyframe snap
        self.enable_keyframe_snap = QCheckBox("Keyframe 정렬 사용 (권장)")
        self.enable_keyframe_snap.setChecked(True)
        self.enable_keyframe_snap.setToolTip("자르는 지점을 I-Frame에 맞춰 깨짐을 방지합니다.")
        custom_params_layout.addRow("", self.enable_keyframe_snap)

        self.custom_params_group.setLayout(custom_params_layout)
        self.custom_params_group.setVisible(False)
        sampling_layout.addWidget(self.custom_params_group)
        
        sampling_group.setLayout(sampling_layout)
        layout.addWidget(sampling_group)

        # 4. 공통 옵션
        options_layout = QVBoxLayout()
        self.gpu_checkbox = QCheckBox("GPU 가속 사용 (CUDA 사용 가능 시)")
        self.gpu_checkbox.setChecked(False)
        self.gpu_checkbox.stateChanged.connect(self.on_gpu_checkbox_changed)
        options_layout.addWidget(self.gpu_checkbox)

        self.save_discarded_checkbox = QCheckBox("버려진 구간(Discarded) 별도 저장")
        options_layout.addWidget(self.save_discarded_checkbox)
        layout.addLayout(options_layout)

        # 실행 버튼
        self.start_sampling_btn = QPushButton("비디오 세그멘테이션 시작")
        self.start_sampling_btn.setMinimumHeight(40)
        self.start_sampling_btn.clicked.connect(self.start_sampling)
        layout.addWidget(self.start_sampling_btn)

        # 로그 뷰어
        self.log_viewer = LogViewer()
        layout.addWidget(self.log_viewer)

        # 진행률 표시
        self.progress_widget = ProgressWidget()
        layout.addWidget(self.progress_widget)

        self.setLayout(layout)

    def browse_input_video(self):
        """입력 비디오 파일 선택"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "입력 비디오 선택",
            "",
            "Video Files (*.mp4 *.mkv *.avi *.mov);;All Files (*)"
        )
        if file_path:
            self.input_video_edit.setText(file_path)
            
            # 출력 폴더 자동 설정 (입력 파일과 같은 폴더의 'segments' 하위 폴더)
            input_path = Path(file_path)
            default_output = input_path.parent / "segments"
            if not self.output_dir_edit.text():
                self.output_dir_edit.setText(str(default_output))

    def browse_output_dir(self):
        """출력 디렉토리 선택"""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "출력 폴더 선택",
            ""
        )
        if dir_path:
            self.output_dir_edit.setText(dir_path)

    def _on_mode_changed(self, index):
        """모드 변경 시 UI 업데이트"""
        is_custom = (index == 1)  # 0: Auto, 1: Custom
        self.custom_params_group.setVisible(is_custom)

    def start_sampling(self):
        """세그멘테이션 시작"""
        input_path_str = self.input_video_edit.text().strip()
        output_path_str = self.output_dir_edit.text().strip()

        if not input_path_str:
            QMessageBox.warning(self, "경고", "입력 비디오를 선택해주세요.")
            return

        if not output_path_str:
            QMessageBox.warning(self, "경고", "출력 폴더를 선택해주세요.")
            return

        input_path = Path(input_path_str)
        output_path = Path(output_path_str)

        if not input_path.exists():
            QMessageBox.critical(self, "오류", f"입력 파일을 찾을 수 없습니다:\n{input_path}")
            return

        # 파라미터 수집
        is_auto_mode = (self.mode_combo.currentIndex() == 0)
        
        params = {
            "mode": "auto" if is_auto_mode else "custom",
            "use_gpu": self.gpu_checkbox.isChecked(),
            "save_discarded": self.save_discarded_checkbox.isChecked()
        }

        if not is_auto_mode:
            params.update({
                "static_threshold": self.static_threshold_spin.value(),
                "min_static_duration": self.min_static_duration_spin.value(),
                "target_segment_duration": self.target_duration_spin.value(),
                "ssim_scale": self.ssim_scale_spin.value(),
                "frame_skip": self.frame_skip_spin.value(),
                "enable_keyframe_snap": self.enable_keyframe_snap.isChecked()
            })

        # UI 비활성화
        self.start_sampling_btn.setEnabled(False)
        self.log_viewer.clear_logs()
        
        # 워커 스레드 시작
        self.worker = SegmentationWorker(
            self.sampler_manager,
            input_path,
            output_path,
            params
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.log_message.connect(self._on_log_message)
        self.worker.finished.connect(self._on_finished)
        
        self.log_viewer.add_log(f"🎬 비디오 세그멘테이션 시작 ({'Auto' if is_auto_mode else 'Custom'})", "INFO")
        if params["use_gpu"]:
            self.log_viewer.add_log("   🚀 GPU 가속 활성화됨", "INFO")
        self.log_viewer.add_log("=" * 60, "INFO")

        self.worker.start()

    def _on_progress(self, current, total):
        if self.progress_widget.total_items != total:
            self.progress_widget.start_progress(total, "비디오 처리 중")
        self.progress_widget.update_progress(current, f"프레임 처리 중... {current:,}/{total:,}")

    def _on_log_message(self, message, level):
        self.log_viewer.add_log(message, level)

    def _on_finished(self, success, message):
        self.progress_widget.finish_progress(success, message)
        self.start_sampling_btn.setEnabled(True)
        self.log_viewer.add_log("=" * 60, "INFO")
        if success:
            self.log_viewer.add_log("✅ 작업 완료!", "INFO")
        else:
            self.log_viewer.add_log("❌ 작업 실패", "ERROR")
        self.log_viewer.add_log("=" * 60, "INFO")
        self.worker = None

    def cancel_segmentation(self):
        if self.worker:
            self.log_viewer.add_log("🛑 사용자 취소 요청...", "WARNING")
            if self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait()
            self.progress_widget.finish_progress(False, "사용자가 취소했습니다.")
            self.log_viewer.add_log("❌ 작업이 취소되었습니다.", "WARNING")
            self.start_sampling_btn.setEnabled(True)
            self.worker = None

    def _verify_gpu_acceleration(self) -> bool:
        """GPU 가속 기능 검증 및 메모리 로깅 (복원됨)"""
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
        """GPU 가속 체크박스 상태 변경 시 (복원됨: 설치 다이얼로그 연동)"""
        
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
                        self.gpu_checkbox.setChecked(False)
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
                    self.gpu_checkbox.setChecked(False)
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
                        self.gpu_checkbox.setChecked(False)
                else:
                    self.log_viewer.add_log("⚠️ PyTorch 설치 취소", "WARNING")
                    self.gpu_checkbox.setChecked(False)

            except Exception as e:
                self.log_viewer.add_log(f"❌ GPU 가속 초기화 실패: {e}", "ERROR")
                QMessageBox.critical(
                    self,
                    "오류",
                    f"GPU 가속 초기화 중 오류가 발생했습니다:\n\n{e}"
                )
                self.gpu_checkbox.setChecked(False)
        else:
            # GPU 가속 비활성화
            self.log_viewer.add_log("GPU 가속 비활성화, CPU 모드로 전환", "INFO")