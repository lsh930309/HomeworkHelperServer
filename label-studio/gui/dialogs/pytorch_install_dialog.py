#!/usr/bin/env python3
"""
PyTorch 설치 진행률 다이얼로그
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QTextEdit, QPushButton, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
import sys
from pathlib import Path

# src.utils 경로 추가
if getattr(sys, 'frozen', False):
    # PyInstaller 패키징 환경
    utils_dir = Path(sys.executable).parent / "_internal" / "src" / "utils"
else:
    # 개발 환경
    utils_dir = Path(__file__).parent.parent.parent.parent / "src" / "utils"

if str(utils_dir.parent) not in sys.path:
    sys.path.insert(0, str(utils_dir.parent))

from utils.pytorch_installer import PyTorchInstaller


class InstallWorker(QThread):
    """PyTorch 설치 워커 스레드"""

    # 시그널 정의
    progress = pyqtSignal(str)  # 진행 메시지
    finished = pyqtSignal(bool)  # 완료 (성공 여부)

    def __init__(self, installer: PyTorchInstaller, cuda_version: str):
        super().__init__()
        self.installer = installer
        self.cuda_version = cuda_version

    def run(self):
        """설치 실행"""
        try:
            success = self.installer.install_pytorch(
                self.cuda_version,
                progress_callback=self.on_progress
            )
            self.finished.emit(success)
        except Exception as e:
            self.progress.emit(f"❌ 설치 중 오류: {e}")
            self.finished.emit(False)

    def on_progress(self, message: str):
        """진행 상황 업데이트"""
        self.progress.emit(message)


class PyTorchInstallDialog(QDialog):
    """PyTorch 설치 진행률 표시 다이얼로그"""

    def __init__(self, parent=None, cuda_version: str = "13.0"):
        super().__init__(parent)
        self.cuda_version = cuda_version
        self.installer = PyTorchInstaller.get_instance()
        self.worker = None
        self.install_success = False

        self.setWindowTitle("PyTorch 설치")
        self.setMinimumSize(600, 400)
        self.setModal(True)  # 모달 다이얼로그

        self.init_ui()
        self.start_installation()

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout()

        # 제목
        title_label = QLabel(f"PyTorch 설치 중 (CUDA {self.cuda_version})")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # 설명
        desc_label = QLabel(
            "GPU 가속을 위한 PyTorch를 자동으로 설치합니다.\n"
            f"설치 위치: {self.installer.install_dir}\n"
            "약 2.5GB, 5-10분 소요됩니다."
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # 진행률 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 무한 진행 (indeterminate)
        layout.addWidget(self.progress_bar)

        # 로그 텍스트
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text)

        # 버튼
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("취소")
        self.cancel_button.clicked.connect(self.on_cancel)
        button_layout.addWidget(self.cancel_button)

        self.close_button = QPushButton("닫기")
        self.close_button.clicked.connect(self.accept)
        self.close_button.setEnabled(False)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def start_installation(self):
        """설치 시작"""
        self.log_text.append(f"[시작] PyTorch CUDA {self.cuda_version} 설치를 시작합니다...\n")

        # 워커 스레드 생성 및 시작
        self.worker = InstallWorker(self.installer, self.cuda_version)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, message: str):
        """진행 상황 업데이트"""
        self.log_text.append(message)
        self.log_text.ensureCursorVisible()  # 자동 스크롤

    def on_finished(self, success: bool):
        """설치 완료"""
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self.install_success = success

        if success:
            self.log_text.append("\n" + "="*60)
            self.log_text.append("✅ PyTorch 설치가 완료되었습니다!")
            self.log_text.append(f"설치 위치: {self.installer.install_dir}")
            self.log_text.append("="*60)

            # sys.path에 추가
            self.installer.add_to_path()

        else:
            self.log_text.append("\n" + "="*60)
            self.log_text.append("❌ PyTorch 설치에 실패했습니다.")
            self.log_text.append("="*60)

        # 버튼 상태 변경
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self.close_button.setFocus()

    def on_cancel(self):
        """설치 취소"""
        reply = QMessageBox.question(
            self,
            "설치 취소",
            "PyTorch 설치를 취소하시겠습니까?\n\n"
            "진행 중인 다운로드는 중단되고,\n"
            "GPU 가속 기능을 사용할 수 없습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.worker and self.worker.isRunning():
                self.log_text.append("\n[취소] 설치를 중단합니다...")
                self.worker.terminate()
                self.worker.wait()

            self.reject()

    def was_successful(self) -> bool:
        """설치 성공 여부 반환"""
        return self.install_success


if __name__ == "__main__":
    # 테스트 코드
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)

    # CUDA 버전 감지
    installer = PyTorchInstaller()
    cuda_version = installer.detect_cuda_version()

    if cuda_version:
        print(f"감지된 CUDA 버전: {cuda_version}")
        dialog = PyTorchInstallDialog(cuda_version=cuda_version)
        result = dialog.exec()

        if result == QDialog.DialogCode.Accepted:
            print("설치 완료!")
            if dialog.was_successful():
                print("PyTorch 설치 성공")
            else:
                print("PyTorch 설치 실패")
        else:
            print("설치 취소됨")
    else:
        print("CUDA 버전을 감지할 수 없습니다.")
        QMessageBox.warning(
            None,
            "CUDA 감지 실패",
            "NVIDIA GPU 또는 드라이버가 설치되어 있지 않습니다."
        )

    sys.exit(app.exec())
