#!/usr/bin/env python3
"""
PyTorch 설치 다이얼로그 (내장 터미널 방식)
사용자가 pip 명령어를 입력하고 다이얼로그 내에서 직접 실행
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QMessageBox, QLineEdit, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPalette
import sys
import subprocess
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
    """pip 설치 워커 스레드"""

    progress = pyqtSignal(str)  # 진행 메시지
    finished = pyqtSignal(bool, str)  # 완료 (성공 여부, 메시지)

    def __init__(self, command: str, installer: PyTorchInstaller):
        super().__init__()
        self.command = command
        self.installer = installer

    def run(self):
        """pip 명령어 실행"""
        try:
            import shlex

            # 명령어 파싱 (경로 공백 처리)
            try:
                parts = shlex.split(self.command.strip())
            except Exception:
                # shlex 실패 시 기본 split 사용
                parts = self.command.strip().split()

            if not parts or parts[0] not in ['pip', 'pip3', 'python', 'python3']:
                self.finished.emit(False, "올바른 pip 명령어가 아닙니다. 'pip install ...' 형식이어야 합니다.")
                return

            # pip 명령어로 정규화
            if parts[0] in ['python', 'python3']:
                if len(parts) < 3 or parts[1] != '-m' or parts[2] not in ['pip', 'pip3']:
                    self.finished.emit(False, "python -m pip install ... 형식이어야 합니다.")
                    return
                # python -m pip → pip로 변환
                parts = ['pip'] + parts[3:]

            # Python 실행 파일 찾기
            python_exe = self.installer._get_python_executable()
            if python_exe is None:
                self.finished.emit(False, "시스템 Python을 찾을 수 없습니다. Python을 PATH에 추가해주세요.")
                return

            self.progress.emit(f"Python 경로: {python_exe}")
            self.progress.emit(f"설치 디렉토리: {self.installer.site_packages}")
            self.progress.emit("")

            # 실제 명령어 구성: python -m pip install ...
            # parts는 이미 shlex로 파싱되어 경로 공백이 올바르게 처리됨
            cmd = [python_exe, '-m'] + parts

            # 로그용 명령어 문자열 (경로에 공백 있으면 따옴표 추가)
            log_cmd = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)
            self.progress.emit(f"실행 명령어: {log_cmd}")
            self.progress.emit("=" * 60)
            self.progress.emit("")

            # 프로세스 실행
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )

            # 실시간 출력
            for line in process.stdout:
                line = line.strip()
                if line:
                    self.progress.emit(line)

            process.wait()

            if process.returncode != 0:
                self.finished.emit(False, f"설치 실패 (종료 코드: {process.returncode})")
                return

            self.progress.emit("")
            self.progress.emit("=" * 60)
            self.progress.emit("✅ pip 설치 완료!")
            self.progress.emit("")

            # 설치 검증
            self.progress.emit("🔍 PyTorch 검증 중...")

            if not self.installer.is_pytorch_installed():
                self.finished.emit(False, "torch 폴더를 찾을 수 없습니다. 설치가 올바르게 완료되지 않았을 수 있습니다.")
                return

            # import 테스트
            self.installer.add_to_path()

            try:
                import torch
                version = torch.__version__
                cuda_available = torch.cuda.is_available()

                self.progress.emit(f"✅ PyTorch {version} 로드 성공")
                self.progress.emit(f"✅ CUDA 사용 가능: {'예' if cuda_available else '아니오'}")

                # 버전 정보 저장
                from datetime import datetime
                import json

                version_info = {
                    "pytorch": version,
                    "cuda": "auto",  # 사용자가 직접 설치
                    "installed_at": datetime.now().isoformat(),
                    "pyqt6_compatible": True,
                    "manual_install": True
                }

                with open(self.installer.version_file, 'w', encoding='utf-8') as f:
                    json.dump(version_info, f, indent=2, ensure_ascii=False)

                self.finished.emit(True, f"PyTorch {version} 설치 및 검증 완료!")

            except ImportError as e:
                self.finished.emit(False, f"import 실패: {e}")
            except Exception as e:
                self.finished.emit(False, f"검증 실패: {e}")

        except Exception as e:
            self.finished.emit(False, f"오류: {e}")


class PyTorchInstallDialog(QDialog):
    """PyTorch 설치 다이얼로그 (내장 터미널)"""

    def __init__(self, parent=None, cuda_version: str = "13.0"):
        super().__init__(parent)
        self.cuda_version = cuda_version
        self.installer = PyTorchInstaller.get_instance()
        self.install_success = False
        self.worker = None

        self.setWindowTitle("PyTorch 설치")
        self.setMinimumSize(800, 600)
        self.setModal(True)

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        layout = QVBoxLayout()

        # 제목
        title_label = QLabel("🐍 PyTorch 설치 (내장 터미널)")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # 설명
        desc_label = QLabel(
            f"감지된 CUDA 버전: <b>{self.cuda_version}</b><br>"
            f"설치 위치: <b>{self.installer.install_dir}</b><br><br>"
            "아래의 pip 명령어를 수정하거나 그대로 사용하여 PyTorch를 설치하세요."
        )
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # 명령어 입력 영역
        cmd_label = QLabel("<b>pip 명령어:</b>")
        layout.addWidget(cmd_label)

        # 권장 명령어 (cu129 사용)
        # 주의: 따옴표 없이 경로만 전달 (subprocess에서 자동으로 처리됨)
        default_cmd = (
            f"pip install torch==2.8.0 torchvision==0.23.0 "
            f"--index-url https://download.pytorch.org/whl/cu129 "
            f"--target {self.installer.site_packages}"
        )

        self.cmd_edit = QTextEdit()
        self.cmd_edit.setPlainText(default_cmd)
        self.cmd_edit.setFont(QFont("Consolas", 10))
        self.cmd_edit.setMaximumHeight(80)

        # 다크/라이트 모드 대응
        palette = self.cmd_edit.palette()
        text_color = palette.color(QPalette.ColorRole.WindowText)
        palette.setColor(QPalette.ColorRole.Text, text_color)
        self.cmd_edit.setPalette(palette)

        layout.addWidget(self.cmd_edit)

        # 실행 버튼
        button_layout = QHBoxLayout()

        info_label = QLabel("💡 명령어를 수정한 후 '설치 시작' 버튼을 클릭하세요")
        info_label.setStyleSheet("QLabel { color: gray; font-style: italic; }")
        button_layout.addWidget(info_label)

        button_layout.addStretch()

        self.install_button = QPushButton("▶️ 설치 시작")
        self.install_button.setStyleSheet("QPushButton { font-weight: bold; padding: 8px 16px; }")
        self.install_button.clicked.connect(self.start_installation)
        button_layout.addWidget(self.install_button)

        layout.addLayout(button_layout)

        # 진행률 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 무한 진행
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 출력 로그
        log_label = QLabel("<b>설치 로그:</b>")
        layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))

        # 다크/라이트 모드 대응
        palette = self.log_text.palette()
        text_color = palette.color(QPalette.ColorRole.WindowText)
        palette.setColor(QPalette.ColorRole.Text, text_color)
        self.log_text.setPalette(palette)

        layout.addWidget(self.log_text)

        # 하단 버튼
        bottom_button_layout = QHBoxLayout()
        bottom_button_layout.addStretch()

        self.cancel_button = QPushButton("취소")
        self.cancel_button.clicked.connect(self.on_cancel)
        bottom_button_layout.addWidget(self.cancel_button)

        self.close_button = QPushButton("닫기")
        self.close_button.clicked.connect(self.accept)
        self.close_button.setEnabled(False)
        bottom_button_layout.addWidget(self.close_button)

        layout.addLayout(bottom_button_layout)

        self.setLayout(layout)

    def start_installation(self):
        """설치 시작"""
        command = self.cmd_edit.toPlainText().strip()

        if not command:
            QMessageBox.warning(self, "명령어 없음", "pip 명령어를 입력해주세요.")
            return

        # UI 상태 변경
        self.cmd_edit.setEnabled(False)
        self.install_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.close_button.setEnabled(False)
        self.progress_bar.setVisible(True)

        self.log_text.clear()
        self.log_text.append("[시작] PyTorch 설치를 시작합니다...\n")
        self.log_text.append(f"명령어: {command}\n")

        # 워커 스레드 시작
        self.worker = InstallWorker(command, self.installer)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, message: str):
        """진행 상황 업데이트"""
        self.log_text.append(message)
        self.log_text.ensureCursorVisible()

    def on_finished(self, success: bool, message: str):
        """설치 완료"""
        self.progress_bar.setVisible(False)
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(True)

        self.log_text.append("\n" + "=" * 60)

        if success:
            self.log_text.append(f"✅ {message}")
            self.log_text.append("=" * 60)
            self.install_success = True

            QMessageBox.information(
                self,
                "설치 완료",
                f"✅ {message}\n\nGPU 가속 기능을 사용할 수 있습니다."
            )
        else:
            self.log_text.append(f"❌ {message}")
            self.log_text.append("=" * 60)

            QMessageBox.critical(
                self,
                "설치 실패",
                f"❌ {message}\n\n명령어를 확인하고 다시 시도해주세요."
            )

            # 재시도 가능하도록 UI 복원
            self.cmd_edit.setEnabled(True)
            self.install_button.setEnabled(True)

        self.worker = None

    def on_cancel(self):
        """설치 취소"""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "설치 취소",
                "설치를 중단하시겠습니까?\n\n"
                "진행 중인 다운로드는 중단되고, GPU 가속 기능을 사용할 수 없습니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.log_text.append("\n[취소] 설치를 중단합니다...")
                self.worker.terminate()
                self.worker.wait()
                self.reject()
        else:
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
