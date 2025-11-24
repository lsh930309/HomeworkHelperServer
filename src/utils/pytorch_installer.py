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

    # 최대 PyQt6 호환 버전 (WinError 1114 DLL 충돌 방지)
    MAX_COMPATIBLE_PYTORCH_VERSION = "2.8.0"
    MAX_COMPATIBLE_TORCHVISION_VERSION = "0.23.0"

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

    # CUDA 버전별 PyTorch 호환성 테이블 (PyQt6 호환 버전 <= 2.8.0 기준)
    # 각 CUDA 버전에서 사용 가능한 최신 PyQt6 호환 PyTorch 버전
    CUDA_PYTORCH_COMPATIBILITY = {
        "13.0": None,  # CUDA 13.0은 PyTorch 2.9.0부터 지원 (PyQt6 비호환)
        "12.6": {"pytorch": "2.8.0", "torchvision": "0.23.0"},
        "12.4": {"pytorch": "2.8.0", "torchvision": "0.23.0"},
        "12.1": {"pytorch": "2.8.0", "torchvision": "0.23.0"},
        "12.0": {"pytorch": "2.4.0", "torchvision": "0.19.0"},
        "11.8": {"pytorch": "2.4.0", "torchvision": "0.19.0"},
        "11.7": {"pytorch": "2.0.0", "torchvision": "0.15.0"},
        "11.6": {"pytorch": "1.13.1", "torchvision": "0.14.1"},
    }

    # CUDA 버전 폴백 체인 (상위 버전 → 하위 버전)
    CUDA_FALLBACK_CHAIN = [
        "13.0", "12.6", "12.4", "12.1", "12.0", "11.8", "11.7", "11.6"
    ]

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

    def get_compatible_pytorch_version(self, cuda_version: str) -> Optional[dict]:
        """
        CUDA 버전에 맞는 PyQt6 호환 PyTorch 버전 찾기 (폴백 포함)

        알고리즘:
        1. 요청된 CUDA 버전에서 호환 버전 확인
        2. 없으면 하위 CUDA 버전으로 폴백하여 재검색
        3. PyQt6 호환 버전(<=2.8.0)이 있으면 반환

        Args:
            cuda_version: "12.1", "13.0" 등

        Returns:
            {"pytorch": "2.8.0", "torchvision": "0.23.0", "cuda": "12.6"}
            또는 None (호환 버전 없음)
        """
        # 1. 현재 CUDA 버전에서 호환 버전 확인
        if cuda_version in self.CUDA_PYTORCH_COMPATIBILITY:
            version_info = self.CUDA_PYTORCH_COMPATIBILITY[cuda_version]
            if version_info is not None:
                return {**version_info, "cuda": cuda_version}

        # 2. 폴백 체인에서 하위 CUDA 버전 검색
        try:
            cuda_idx = self.CUDA_FALLBACK_CHAIN.index(cuda_version)
        except ValueError:
            # CUDA 버전이 체인에 없으면 가장 가까운 하위 버전 찾기
            cuda_float = float(cuda_version)
            cuda_idx = -1
            for i, fallback_version in enumerate(self.CUDA_FALLBACK_CHAIN):
                if float(fallback_version) <= cuda_float:
                    cuda_idx = i
                    break

        if cuda_idx == -1:
            return None

        # 3. 하위 CUDA 버전들을 순회하며 호환 버전 찾기
        for fallback_cuda in self.CUDA_FALLBACK_CHAIN[cuda_idx + 1:]:
            if fallback_cuda in self.CUDA_PYTORCH_COMPATIBILITY:
                version_info = self.CUDA_PYTORCH_COMPATIBILITY[fallback_cuda]
                if version_info is not None:
                    return {**version_info, "cuda": fallback_cuda}

        return None

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

    def _get_python_executable(self) -> Optional[str]:
        """
        실제 Python 실행 파일 경로 반환 (PyInstaller 환경 대응)

        Returns:
            Python 경로 또는 None
        """
        import shutil

        if getattr(sys, 'frozen', False):
            # PyInstaller 환경: 시스템 Python 찾기
            python_exe = shutil.which('python')
            if python_exe:
                # 버전 확인
                try:
                    result = subprocess.run(
                        [python_exe, "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    if result.returncode == 0:
                        return python_exe
                except:
                    pass

            return None
        else:
            # 개발 환경
            return sys.executable

    def install_pytorch(
        self,
        cuda_version: str,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        pip를 사용하여 PyTorch 설치 (PyQt6 호환 버전, CUDA 폴백 지원)

        Args:
            cuda_version: "12.1", "13.0" 등 (감지된 CUDA 버전)
            progress_callback: 진행 상황 메시지 콜백

        Returns:
            성공 여부
        """
        try:
            # 1. Python 실행 파일 찾기
            python_exe = self._get_python_executable()

            if python_exe is None:
                if progress_callback:
                    progress_callback("❌ 시스템 Python을 찾을 수 없습니다.")
                    progress_callback("   해결: Python을 설치하고 PATH에 추가해주세요.")
                    progress_callback("   다운로드: https://www.python.org/downloads/")
                return False

            if progress_callback:
                progress_callback(f"Python 경로: {python_exe}")

            # 2. 호환 가능한 PyTorch 버전 찾기 (폴백 포함)
            version_info = self.get_compatible_pytorch_version(cuda_version)

            if version_info is None:
                if progress_callback:
                    progress_callback(f"❌ CUDA {cuda_version}와 호환되는 PyQt6 호환 PyTorch를 찾을 수 없습니다.")
                    progress_callback("   가장 낮은 CUDA 11.6 이상이 필요합니다.")
                return False

            pytorch_version = version_info["pytorch"]
            torchvision_version = version_info["torchvision"]
            target_cuda = version_info["cuda"]

            if progress_callback:
                if target_cuda != cuda_version:
                    progress_callback(f"⚠️ CUDA {cuda_version}는 PyQt6 호환 PyTorch를 지원하지 않습니다.")
                    progress_callback(f"   CUDA {target_cuda} 호환 버전으로 폴백합니다.")
                    progress_callback(f"   (하위 호환성으로 정상 작동합니다)")
                progress_callback(f"설치 버전: PyTorch {pytorch_version}, torchvision {torchvision_version}")

            # 3. 설치 디렉토리 준비
            self.install_dir.mkdir(parents=True, exist_ok=True)
            self.site_packages.mkdir(parents=True, exist_ok=True)

            if progress_callback:
                progress_callback(f"설치 디렉토리 준비: {self.install_dir}")

            # 4. pip 설치 명령어 생성 (PyQt6 호환 버전 사용)
            cuda_tag = target_cuda.replace(".", "")  # "12.6" → "cu126"
            index_url = f"https://download.pytorch.org/whl/cu{cuda_tag}"

            if progress_callback:
                progress_callback(f"PyTorch {pytorch_version} (PyQt6 호환) 다운로드 중...")

            cmd = [
                python_exe, "-m", "pip", "install",
                f"torch=={pytorch_version}",
                f"torchvision=={torchvision_version}",
                "--index-url", index_url,
                "--target", str(self.site_packages),
                "--no-warn-script-location",
                "--no-cache-dir"
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

            # 6. 설치 검증 (중요!)
            if progress_callback:
                progress_callback("🔍 설치 검증 중...")

            sys.path.insert(0, str(self.site_packages))
            try:
                import torch
                installed_version = torch.__version__

                if progress_callback:
                    progress_callback(f"✅ 검증: PyTorch {installed_version} 로드 성공")

                # 7. 버전 정보 저장
                from datetime import datetime
                save_version_info = {
                    "pytorch": installed_version,
                    "cuda": target_cuda,  # 실제 설치된 CUDA 버전
                    "detected_cuda": cuda_version,  # 감지된 CUDA 버전
                    "installed_at": datetime.now().isoformat(),
                    "pyqt6_compatible": True  # PyQt6 호환 버전임을 표시
                }

                with open(self.version_file, 'w', encoding='utf-8') as f:
                    json.dump(save_version_info, f, indent=2, ensure_ascii=False)

                with open(self.cuda_file, 'w', encoding='utf-8') as f:
                    f.write(target_cuda)

                if progress_callback:
                    progress_callback(f"✅ PyTorch {installed_version} 설치 완료!")

                return True

            except ImportError as e:
                if progress_callback:
                    progress_callback(f"❌ 설치 검증 실패: {e}")
                    progress_callback("   pip 설치는 완료되었으나 import에 실패했습니다.")
                return False

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
