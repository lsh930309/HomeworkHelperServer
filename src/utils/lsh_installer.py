#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Label Studio Helper 설치 도우미

HomeworkHelper에서 Label Studio Helper 독립 앱을 다운로드/설치하는 유틸리티입니다.
GitHub Release에서 최신 버전을 다운로드하고 설치합니다.
"""

import os
import sys
import json
import shutil
import zipfile
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, Callable, Tuple
import threading

# HTTP 요청용
try:
    import requests
except ImportError:
    requests = None


class LabelStudioHelperInstaller:
    """Label Studio Helper 설치 도우미"""
    
    # GitHub 저장소 정보
    GITHUB_OWNER = "lsh930309"
    GITHUB_REPO = "LabelStudioHelper"
    GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    
    # 설치 경로
    DEFAULT_INSTALL_DIR = Path(os.getenv('LOCALAPPDATA', os.path.expanduser('~'))) / "LabelStudioHelper"
    
    # 앱 실행 파일 이름
    APP_EXE_NAME = "label_studio_helper.exe"
    
    def __init__(self, install_dir: Optional[Path] = None):
        """
        Args:
            install_dir: 설치 디렉토리 (기본값: %LOCALAPPDATA%/LabelStudioHelper)
        """
        self.install_dir = Path(install_dir) if install_dir else self.DEFAULT_INSTALL_DIR
        self.app_exe_path = self.install_dir / self.APP_EXE_NAME
        self.version_file = self.install_dir / "version.json"
    
    def is_installed(self) -> bool:
        """Label Studio Helper 설치 여부 확인"""
        return self.app_exe_path.exists()
    
    def get_installed_version(self) -> Optional[str]:
        """설치된 버전 반환"""
        if not self.version_file.exists():
            return None
        try:
            with open(self.version_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("version")
        except Exception:
            return None
    
    def get_latest_release_info(self) -> Optional[dict]:
        """
        GitHub에서 최신 릴리스 정보 가져오기
        
        Returns:
            {"version": "v1.0.0", "download_url": "...", "size_mb": 50.5}
            또는 None (실패 시)
        """
        if requests is None:
            print("⚠️ requests 모듈이 필요합니다.")
            return None
        
        try:
            headers = {"Accept": "application/vnd.github.v3+json"}
            response = requests.get(self.GITHUB_API_URL, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            tag_name = data.get("tag_name", "unknown")
            
            # ZIP 파일 asset 찾기
            for asset in data.get("assets", []):
                if asset["name"].endswith(".zip"):
                    return {
                        "version": tag_name,
                        "download_url": asset["browser_download_url"],
                        "size_mb": asset["size"] / (1024 * 1024),
                        "name": asset["name"]
                    }
            
            return None
            
        except Exception as e:
            print(f"⚠️ 릴리스 정보 가져오기 실패: {e}")
            return None
    
    def download_and_install(
        self,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Tuple[bool, str]:
        """
        최신 버전 다운로드 및 설치
        
        Args:
            progress_callback: (message, progress 0.0~1.0) 콜백
        
        Returns:
            (성공 여부, 메시지)
        """
        if requests is None:
            return False, "requests 모듈이 설치되지 않았습니다."
        
        def update_progress(msg: str, pct: float):
            if progress_callback:
                progress_callback(msg, pct)
            print(f"[{pct*100:.0f}%] {msg}")
        
        try:
            # 1. 릴리스 정보 가져오기
            update_progress("최신 버전 정보 확인 중...", 0.0)
            release_info = self.get_latest_release_info()
            
            if not release_info:
                return False, "GitHub에서 릴리스 정보를 찾을 수 없습니다."
            
            version = release_info["version"]
            download_url = release_info["download_url"]
            size_mb = release_info["size_mb"]
            
            update_progress(f"버전 {version} ({size_mb:.1f}MB) 다운로드 중...", 0.1)
            
            # 2. 임시 폴더에 다운로드
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_zip = Path(temp_dir) / release_info["name"]
                
                # 다운로드 (진행률 표시)
                response = requests.get(download_url, stream=True, timeout=300)
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(temp_zip, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            pct = 0.1 + (downloaded / total_size * 0.5)
                            update_progress(f"다운로드 중... ({downloaded // (1024*1024)}/{size_mb:.0f} MB)", pct)
                
                update_progress("압축 해제 중...", 0.6)
                
                # 3. 압축 해제
                extract_dir = Path(temp_dir) / "extracted"
                with zipfile.ZipFile(temp_zip, 'r') as zipf:
                    zipf.extractall(extract_dir)
                
                # 4. 설치 디렉토리 준비
                update_progress("설치 중...", 0.7)
                
                if self.install_dir.exists():
                    # 기존 설치 백업 또는 제거
                    shutil.rmtree(self.install_dir)
                
                self.install_dir.mkdir(parents=True, exist_ok=True)
                
                # 5. 파일 복사
                # 압축 파일 구조에 따라 적절한 경로 찾기
                extracted_app_dir = None
                for item in extract_dir.iterdir():
                    if item.is_dir():
                        # 첫 번째 디렉토리를 앱 폴더로 간주
                        extracted_app_dir = item
                        break
                
                if extracted_app_dir:
                    # 디렉토리 내용을 설치 경로로 복사
                    for item in extracted_app_dir.iterdir():
                        dest = self.install_dir / item.name
                        if item.is_dir():
                            shutil.copytree(item, dest)
                        else:
                            shutil.copy2(item, dest)
                else:
                    # ZIP 루트에 파일들이 바로 있는 경우
                    for item in extract_dir.iterdir():
                        dest = self.install_dir / item.name
                        if item.is_dir():
                            shutil.copytree(item, dest)
                        else:
                            shutil.copy2(item, dest)
                
                # 6. 버전 정보 저장
                update_progress("설치 완료 처리 중...", 0.9)
                
                with open(self.version_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        "version": version,
                        "installed_at": __import__('datetime').datetime.now().isoformat()
                    }, f, indent=2)
                
                update_progress("설치 완료!", 1.0)
                
                return True, f"Label Studio Helper {version} 설치 완료!\n경로: {self.install_dir}"
        
        except Exception as e:
            return False, f"설치 중 오류 발생: {e}"
    
    def launch(self) -> bool:
        """
        Label Studio Helper 실행
        
        Returns:
            실행 성공 여부
        """
        if not self.is_installed():
            print("❌ Label Studio Helper가 설치되지 않았습니다.")
            return False
        
        try:
            # 일반 사용자 권한으로 실행 (관리자 권한 제외)
            subprocess.Popen(
                [str(self.app_exe_path)],
                cwd=str(self.install_dir),
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            print(f"✅ Label Studio Helper 실행됨: {self.app_exe_path}")
            return True
            
        except Exception as e:
            print(f"❌ 실행 실패: {e}")
            return False
    
    def uninstall(self) -> bool:
        """
        Label Studio Helper 제거
        
        Returns:
            제거 성공 여부
        """
        try:
            if self.install_dir.exists():
                shutil.rmtree(self.install_dir)
                print(f"✅ Label Studio Helper 제거 완료: {self.install_dir}")
            return True
        except Exception as e:
            print(f"❌ 제거 실패: {e}")
            return False


# PyQt6 GUI 다이얼로그 (선택적)
try:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
        QProgressBar, QMessageBox, QGroupBox
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    
    class InstallWorker(QThread):
        """백그라운드 설치 워커"""
        progress = pyqtSignal(str, float)  # message, percentage
        finished = pyqtSignal(bool, str)   # success, message
        
        def __init__(self, installer: LabelStudioHelperInstaller):
            super().__init__()
            self.installer = installer
        
        def run(self):
            success, msg = self.installer.download_and_install(
                progress_callback=lambda msg, pct: self.progress.emit(msg, pct)
            )
            self.finished.emit(success, msg)
    
    class LabelStudioHelperDialog(QDialog):
        """Label Studio Helper 설치/관리 다이얼로그"""
        
        def __init__(self, parent=None):
            super().__init__(parent)
            self.installer = LabelStudioHelperInstaller()
            self.worker = None
            self._setup_ui()
            self._update_ui_state()
        
        def _setup_ui(self):
            self.setWindowTitle("Label Studio Helper")
            self.setMinimumWidth(400)
            
            layout = QVBoxLayout(self)
            
            # 정보 그룹
            info_group = QGroupBox("설치 정보")
            info_layout = QVBoxLayout(info_group)
            
            self.status_label = QLabel()
            info_layout.addWidget(self.status_label)
            
            self.version_label = QLabel()
            info_layout.addWidget(self.version_label)
            
            self.path_label = QLabel(f"설치 경로: {self.installer.install_dir}")
            self.path_label.setWordWrap(True)
            info_layout.addWidget(self.path_label)
            
            layout.addWidget(info_group)
            
            # 진행률
            self.progress_bar = QProgressBar()
            self.progress_bar.setVisible(False)
            layout.addWidget(self.progress_bar)
            
            self.progress_label = QLabel()
            self.progress_label.setVisible(False)
            layout.addWidget(self.progress_label)
            
            # 버튼 영역
            btn_layout = QHBoxLayout()
            
            self.install_btn = QPushButton("📥 다운로드/설치")
            self.install_btn.clicked.connect(self._on_install_clicked)
            btn_layout.addWidget(self.install_btn)
            
            self.launch_btn = QPushButton("🚀 실행")
            self.launch_btn.clicked.connect(self._on_launch_clicked)
            btn_layout.addWidget(self.launch_btn)
            
            self.uninstall_btn = QPushButton("🗑️ 제거")
            self.uninstall_btn.clicked.connect(self._on_uninstall_clicked)
            btn_layout.addWidget(self.uninstall_btn)
            
            layout.addLayout(btn_layout)
            
            # 닫기 버튼
            close_btn = QPushButton("닫기")
            close_btn.clicked.connect(self.accept)
            layout.addWidget(close_btn)
        
        def _update_ui_state(self):
            """UI 상태 업데이트"""
            is_installed = self.installer.is_installed()
            version = self.installer.get_installed_version()
            
            if is_installed:
                self.status_label.setText("✅ 설치됨")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
                self.version_label.setText(f"버전: {version or '알 수 없음'}")
                self.launch_btn.setEnabled(True)
                self.uninstall_btn.setEnabled(True)
                self.install_btn.setText("📥 업데이트 확인")
            else:
                self.status_label.setText("❌ 미설치")
                self.status_label.setStyleSheet("color: red; font-weight: bold;")
                self.version_label.setText("")
                self.launch_btn.setEnabled(False)
                self.uninstall_btn.setEnabled(False)
                self.install_btn.setText("📥 다운로드/설치")
        
        def _on_install_clicked(self):
            """설치 버튼 클릭"""
            self.install_btn.setEnabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.progress_label.setVisible(True)
            
            self.worker = InstallWorker(self.installer)
            self.worker.progress.connect(self._on_progress)
            self.worker.finished.connect(self._on_install_finished)
            self.worker.start()
        
        def _on_progress(self, msg: str, pct: float):
            """진행률 업데이트"""
            self.progress_bar.setValue(int(pct * 100))
            self.progress_label.setText(msg)
        
        def _on_install_finished(self, success: bool, msg: str):
            """설치 완료"""
            self.progress_bar.setVisible(False)
            self.progress_label.setVisible(False)
            self.install_btn.setEnabled(True)
            
            if success:
                QMessageBox.information(self, "설치 완료", msg)
            else:
                QMessageBox.critical(self, "설치 실패", msg)
            
            self._update_ui_state()
        
        def _on_launch_clicked(self):
            """실행 버튼 클릭"""
            if self.installer.launch():
                self.accept()  # 다이얼로그 닫기
            else:
                QMessageBox.critical(self, "실행 실패", "Label Studio Helper를 실행할 수 없습니다.")
        
        def _on_uninstall_clicked(self):
            """제거 버튼 클릭"""
            reply = QMessageBox.question(
                self, "제거 확인",
                "Label Studio Helper를 제거하시겠습니까?\n\n"
                f"경로: {self.installer.install_dir}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                if self.installer.uninstall():
                    QMessageBox.information(self, "제거 완료", "Label Studio Helper가 제거되었습니다.")
                else:
                    QMessageBox.critical(self, "제거 실패", "제거 중 오류가 발생했습니다.")
                self._update_ui_state()

except ImportError:
    # PyQt6가 없는 환경
    LabelStudioHelperDialog = None


# CLI 테스트
if __name__ == "__main__":
    installer = LabelStudioHelperInstaller()
    
    print("=== Label Studio Helper 설치 도우미 ===\n")
    print(f"설치 경로: {installer.install_dir}")
    print(f"설치 여부: {'✅ 설치됨' if installer.is_installed() else '❌ 미설치'}")
    
    if installer.is_installed():
        print(f"설치 버전: {installer.get_installed_version()}")
    
    print("\n최신 릴리스 확인 중...")
    release_info = installer.get_latest_release_info()
    if release_info:
        print(f"최신 버전: {release_info['version']} ({release_info['size_mb']:.1f} MB)")
    else:
        print("릴리스 정보를 찾을 수 없습니다.")
