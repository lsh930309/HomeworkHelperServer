#!/usr/bin/env python3
"""
PyTorch 자동 설치 관리자
사용자의 CUDA 버전을 감지하고 적절한 PyTorch를 %APPDATA%에 설치합니다.
"""

import sys
import os
import subprocess
import re
from pathlib import Path
from typing import Optional, Callable
import json


class PyTorchInstaller:
    """
    PyTorch 자동 설치 및 관리

    설치 위치: %APPDATA%/HomeworkHelper/pytorch/
    """

    # 싱글톤 인스턴스
    _instance: Optional['PyTorchInstaller'] = None

    # NVIDIA 드라이버 버전 → CUDA 버전 매핑
    CUDA_DRIVER_MAP = {
        "581": "13.0",  # Driver 581.x → CUDA 13.0
        "570": "12.6",
        "560": "12.6",
        "555": "12.5",
        "550": "12.4",
        "545": "12.3",
        "535": "12.2",
        "530": "12.1",
        "525": "12.0",
        "520": "11.8",
        "515": "11.7",
        "510": "11.6",
    }

    def __init__(self, install_dir: Optional[Path] = None):
        """
        Args:
            install_dir: PyTorch 설치 디렉토리 (기본값: %APPDATA%/HomeworkHelper/pytorch)
        """
        if install_dir is None:
            # %APPDATA%/HomeworkHelper/pytorch
            appdata = os.getenv('APPDATA')
            if not appdata:
                appdata = os.path.expanduser('~')
            self.install_dir = Path(appdata) / "HomeworkHelper" / "pytorch"
        else:
            self.install_dir = Path(install_dir)

        self.site_packages = self.install_dir / "Lib" / "site-packages"
        self.version_file = self.install_dir / "version.txt"
        self.cuda_file = self.install_dir / "cuda_version.txt"

    @classmethod
    def get_instance(cls, install_dir: Optional[Path] = None) -> 'PyTorchInstaller':
        """싱글톤 인스턴스 반환"""
        if cls._instance is None:
            cls._instance = cls(install_dir)
        return cls._instance

    def detect_cuda_version(self) -> Optional[str]:
        """
        nvidia-smi로 CUDA 버전 감지

        Returns:
            "12.1", "13.0" 형식의 CUDA 버전 또는 None (GPU 없음)
        """
        try:
            # nvidia-smi로 드라이버 버전 확인
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode != 0:
                return None

            driver_version = result.stdout.strip()
            if not driver_version:
                return None

            # 드라이버 버전에서 메이저 버전 추출 (예: "581.57" → "581")
            match = re.match(r"(\d+)\.", driver_version)
            if not match:
                return None

            driver_major = match.group(1)

            # 매핑 테이블에서 CUDA 버전 찾기
            for driver_prefix, cuda_version in self.CUDA_DRIVER_MAP.items():
                if driver_major >= driver_prefix:
                    return cuda_version

            # 매핑에 없는 경우 최신 버전 반환
            return "13.0"

        except FileNotFoundError:
            # nvidia-smi 없음 = NVIDIA GPU 없음
            return None
        except subprocess.TimeoutExpired:
            print("⚠️ nvidia-smi 응답 시간 초과")
            return None
        except Exception as e:
            print(f"⚠️ CUDA 감지 중 오류: {e}")
            return None

    def is_pytorch_installed(self) -> bool:
        """PyTorch 설치 여부 확인"""
        torch_path = self.site_packages / "torch"
        return torch_path.exists() and self.version_file.exists()

    def get_installed_version(self) -> Optional[dict]:
        """
        설치된 PyTorch 버전 정보 반환

        Returns:
            {"pytorch": "2.9.1", "cuda": "13.0", "installed_at": "2025-11-24T13:45:00"}
            또는 None (미설치)
        """
        if not self.version_file.exists():
            return None

        try:
            with open(self.version_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 버전 파일 읽기 실패: {e}")
            return None

    def install_pytorch(
        self,
        cuda_version: str,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        pip를 사용하여 PyTorch 설치

        Args:
            cuda_version: "12.1", "13.0" 등
            progress_callback: 진행 상황 메시지 콜백

        Returns:
            성공 여부
        """
        try:
            # 1. 설치 디렉토리 준비
            self.install_dir.mkdir(parents=True, exist_ok=True)
            self.site_packages.mkdir(parents=True, exist_ok=True)

            if progress_callback:
                progress_callback(f"설치 디렉토리 준비: {self.install_dir}")

            # 2. pip 설치 명령어 생성
            cuda_tag = cuda_version.replace(".", "")  # "13.0" → "cu130"
            index_url = f"https://download.pytorch.org/whl/cu{cuda_tag}"

            if progress_callback:
                progress_callback(f"PyTorch CUDA {cuda_version} 다운로드 중...")

            cmd = [
                sys.executable, "-m", "pip", "install",
                "torch", "torchvision",
                "--index-url", index_url,
                "--target", str(self.site_packages),
                "--no-warn-script-location",
                "--no-cache-dir"  # 캐시 사용 안 함 (항상 최신 다운로드)
            ]

            # 3. 서브프로세스 실행 및 진행률 추적
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # 4. 실시간 로그 출력
            for line in process.stdout:
                line = line.strip()
                if line:
                    print(line)  # 콘솔 로그
                    if progress_callback:
                        progress_callback(line)

            process.wait()

            # 5. 결과 확인
            if process.returncode != 0:
                if progress_callback:
                    progress_callback(f"❌ 설치 실패 (종료 코드: {process.returncode})")
                return False

            # 6. 버전 정보 저장
            from datetime import datetime
            version_info = {
                "pytorch": "latest",  # pip가 설치한 최신 버전
                "cuda": cuda_version,
                "installed_at": datetime.now().isoformat()
            }

            with open(self.version_file, 'w', encoding='utf-8') as f:
                json.dump(version_info, f, indent=2, ensure_ascii=False)

            with open(self.cuda_file, 'w', encoding='utf-8') as f:
                f.write(cuda_version)

            if progress_callback:
                progress_callback(f"✅ PyTorch 설치 완료: {self.install_dir}")

            return True

        except Exception as e:
            error_msg = f"❌ PyTorch 설치 중 오류: {e}"
            print(error_msg)
            if progress_callback:
                progress_callback(error_msg)
            return False

    def uninstall_pytorch(self) -> bool:
        """
        PyTorch 제거

        Returns:
            성공 여부
        """
        try:
            if self.install_dir.exists():
                import shutil
                shutil.rmtree(self.install_dir)
                print(f"✅ PyTorch 제거 완료: {self.install_dir}")
                return True
            else:
                print("⚠️ PyTorch가 설치되어 있지 않습니다.")
                return True
        except Exception as e:
            print(f"❌ PyTorch 제거 실패: {e}")
            return False

    def add_to_path(self) -> bool:
        """
        PyTorch 설치 경로를 sys.path에 추가

        Returns:
            성공 여부
        """
        if not self.site_packages.exists():
            print(f"⚠️ PyTorch 설치 경로가 없습니다: {self.site_packages}")
            return False

        site_packages_str = str(self.site_packages)

        if site_packages_str not in sys.path:
            sys.path.insert(0, site_packages_str)
            print(f"✅ PyTorch 경로 추가: {site_packages_str}")

        return True

    def get_install_info(self) -> dict:
        """
        설치 정보 반환 (GUI 표시용)

        Returns:
            {
                "installed": bool,
                "version": str,
                "cuda": str,
                "path": str,
                "size_mb": float
            }
        """
        info = {
            "installed": False,
            "version": "미설치",
            "cuda": "N/A",
            "path": str(self.install_dir),
            "size_mb": 0.0
        }

        if self.is_pytorch_installed():
            version_data = self.get_installed_version()
            if version_data:
                info["installed"] = True
                info["version"] = version_data.get("pytorch", "unknown")
                info["cuda"] = version_data.get("cuda", "unknown")

            # 디렉토리 크기 계산
            try:
                total_size = sum(
                    f.stat().st_size
                    for f in self.install_dir.rglob('*')
                    if f.is_file()
                )
                info["size_mb"] = total_size / (1024 * 1024)
            except:
                pass

        return info


# 편의 함수
def get_pytorch_installer() -> PyTorchInstaller:
    """PyTorchInstaller 싱글톤 인스턴스 반환"""
    return PyTorchInstaller.get_instance()


if __name__ == "__main__":
    # 테스트 코드
    installer = PyTorchInstaller()

    print("=== PyTorch Installer 테스트 ===\n")

    # 1. CUDA 버전 감지
    cuda_version = installer.detect_cuda_version()
    print(f"감지된 CUDA 버전: {cuda_version}")

    # 2. 설치 상태 확인
    print(f"\nPyTorch 설치 여부: {installer.is_pytorch_installed()}")

    if installer.is_pytorch_installed():
        version_info = installer.get_installed_version()
        print(f"설치된 버전: {version_info}")

        install_info = installer.get_install_info()
        print(f"\n설치 정보:")
        for key, value in install_info.items():
            print(f"  {key}: {value}")
