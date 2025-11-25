#!/usr/bin/env python3
"""
SSIM 기반 스마트 비디오 세그멘테이션
비디오를 동적 배경 구간으로 분할하여 YOLO 과적합 방지 및 라벨링 효율 극대화
UI는 고정되고 배경만 변하는 구간 선택

사용법:
    python tools/video_segmenter.py --input datasets/raw/gameplay.mp4 \
                                     --output datasets/clips/ \
                                     --dynamic-low 0.4 \
                                     --dynamic-high 0.8 \
                                     --min-duration 5
"""

import argparse
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass
import json
from datetime import datetime
from skimage.metrics import structural_similarity as ssim
import subprocess
import shutil
import sys


def refresh_system_path():
    """
    시스템 PATH 환경변수를 레지스트리에서 새로고침 (Windows 전용)
    winget 설치 후 현재 프로세스에서 PATH를 즉시 사용하기 위함
    """
    if sys.platform != 'win32':
        return

    try:
        import winreg
        import os

        # 시스템 PATH 읽기
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
                           0, winreg.KEY_READ) as key:
            system_path, _ = winreg.QueryValueEx(key, 'Path')

        # 사용자 PATH 읽기
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r'Environment',
                           0, winreg.KEY_READ) as key:
            try:
                user_path, _ = winreg.QueryValueEx(key, 'Path')
            except FileNotFoundError:
                user_path = ''

        # 현재 프로세스의 PATH 업데이트
        combined_path = f"{user_path};{system_path}" if user_path else system_path
        os.environ['PATH'] = combined_path

    except Exception as e:
        # PATH 새로고침 실패는 치명적이지 않으므로 무시
        pass


def check_and_install_ffmpeg() -> bool:
    """
    ffmpeg 설치 여부 확인 및 자동 설치

    Returns:
        bool: ffmpeg가 사용 가능하면 True, 설치 실패하면 False
    """
    # ffmpeg가 이미 PATH에 있는지 확인
    if shutil.which('ffmpeg') is not None:
        return True

    print("⚠️ ffmpeg를 찾을 수 없습니다.")
    print("🔧 ffmpeg를 자동으로 설치합니다 (winget 사용)...")

    try:
        # winget으로 ffmpeg 설치 시도
        result = subprocess.run(
            ['winget', 'install', 'Gyan.FFmpeg', '--accept-source-agreements', '--accept-package-agreements'],
            capture_output=True,
            text=True,
            timeout=300  # 5분 타임아웃
        )

        if result.returncode == 0:
            print("✅ ffmpeg 설치 완료!")

            # PATH 새로고침 시도
            print("🔄 PATH 환경변수 새로고침 중...")
            refresh_system_path()

            # 설치 후 다시 확인
            if shutil.which('ffmpeg') is not None:
                print("✅ ffmpeg를 바로 사용할 수 있습니다!")
                return True
            else:
                print("   ⚠️ 설치는 완료되었으나 PATH에서 ffmpeg를 찾을 수 없습니다.")
                print("   ℹ️ 다음 중 하나를 시도해주세요:")
                print("      1. 터미널을 재시작한 후 다시 실행")
                print("      2. 시스템을 재부팅")
                return False
        else:
            print(f"❌ ffmpeg 설치 실패")
            if result.stderr:
                print(f"   오류 메시지: {result.stderr[:200]}")
            print("   ℹ️ 수동 설치 방법:")
            print("      1. 터미널에서 'winget install Gyan.FFmpeg' 실행")
            print("      2. 또는 https://www.gyan.dev/ffmpeg/builds/ 에서 다운로드")
            return False

    except FileNotFoundError:
        print("❌ winget을 찾을 수 없습니다.")
        print("   ℹ️ Windows 10 1809 이상 또는 Windows 11이 필요합니다.")
        print("   ℹ️ 수동 설치: https://www.gyan.dev/ffmpeg/builds/")
        return False
    except subprocess.TimeoutExpired:
        print("❌ ffmpeg 설치 시간 초과 (5분)")
        print("   ℹ️ 네트워크 상태를 확인하고 수동으로 설치해주세요.")
        return False
    except Exception as e:
        print(f"❌ ffmpeg 설치 중 예상치 못한 오류: {e}")
        return False


class PyAVVideoReader:
    """
    PyAV를 사용한 비디오 리더 (OpenCV가 지원하지 않는 코덱 처리)
    AV1, H.265, VP9 등 모든 FFmpeg 지원 코덱을 무손실로 읽을 수 있음
    """

    def __init__(self, video_path: Path):
        """
        Args:
            video_path: 비디오 파일 경로
        """
        self.video_path = video_path
        self.container = None
        self.video_stream = None
        self.fps = None
        self.total_frames = None
        self.width = None
        self.height = None
        self._frame_generator = None

    def open(self) -> bool:
        """
        비디오 파일 열기

        Returns:
            bool: 성공 여부
        """
        try:
            import av

            self.container = av.open(str(self.video_path))
            self.video_stream = self.container.streams.video[0]

            # 비디오 정보 추출
            self.fps = float(self.video_stream.average_rate)
            self.total_frames = self.video_stream.frames
            self.width = self.video_stream.width
            self.height = self.video_stream.height

            # total_frames가 0이면 duration으로 추정
            if self.total_frames == 0 and self.container.duration:
                self.total_frames = int(self.container.duration * self.fps / av.time_base)

            # 프레임 제너레이터 초기화
            self._frame_generator = self.container.decode(video=0)

            print(f"✅ PyAV로 비디오 열기 성공")
            print(f"   코덱: {self.video_stream.codec_context.name}")

            return True

        except ImportError:
            print("⚠️ PyAV가 설치되지 않았습니다.")
            print("   설치 방법: pip install av")
            return False
        except Exception as e:
            print(f"⚠️ PyAV로 비디오 열기 실패: {e}")
            return False

    def read(self):
        """
        다음 프레임 읽기 (OpenCV의 cap.read()와 동일한 인터페이스)

        Returns:
            tuple: (success, frame_bgr) - OpenCV 형식의 BGR numpy array
        """
        try:
            frame = next(self._frame_generator)
            # BGR 포맷으로 변환 (OpenCV 호환)
            img = frame.to_ndarray(format='bgr24')
            return True, img
        except StopIteration:
            return False, None
        except Exception as e:
            return False, None

    def grab(self):
        """
        프레임을 건너뛰기 (OpenCV의 cap.grab()와 동일한 인터페이스)
        PyAV는 grab을 직접 지원하지 않으므로 read하고 버림

        Returns:
            bool: 성공 여부
        """
        try:
            frame = next(self._frame_generator)
            return True
        except StopIteration:
            return False
        except Exception as e:
            return False

    def release(self):
        """리소스 해제"""
        if self.container:
            self.container.close()
            self.container = None

    def isOpened(self) -> bool:
        """비디오가 열려있는지 확인"""
        return self.container is not None


@dataclass
class VideoSegment:
    """비디오 세그먼트 정보"""
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    duration: float
    avg_ssim: float  # 구간 내 평균 SSIM (안정성 지표)


@dataclass
class SegmentConfig:
    """세그멘테이션 설정"""
    # 장면 전환 감지 (너무 낮은 SSIM)
    scene_change_threshold: float = 0.3  # SSIM이 이보다 낮으면 장면 전환 (제외)

    # 정적 구간 감지 (너무 높은 SSIM = 잠수 구간)
    static_threshold: float = 0.95       # SSIM이 이보다 높으면 너무 정적 (제외)
    min_dynamic_frames: int = 30         # 최소 동적 프레임 수 (1초@30fps)

    # 세그먼트 제약
    min_duration: float = 5.0            # 최소 세그먼트 길이 (초)
    max_duration: float = 60.0           # 최대 세그먼트 길이 (초)
    max_segments: Optional[int] = None   # 최대 세그먼트 수

    # 성능 최적화
    ssim_scale: float = 1.0              # SSIM 계산 시 해상도 스케일 (0.25 = 4배 빠름, 출력은 원본 유지)
    frame_skip: int = 1                  # 프레임 스킵 (1=모든 프레임, 3=3프레임마다)
    use_gpu: bool = False                # GPU 가속 사용 (CUDA 사용 가능 시)

    # 실험 기능
    save_discarded: bool = False         # 채택되지 않은 구간도 별도 저장

    # 출력 설정
    output_codec: str = "mp4v"           # 출력 코덱
    output_fps: Optional[int] = None     # 출력 FPS (None이면 원본)


class VideoSegmenter:
    """SSIM 기반 비디오 세그멘테이션"""

    def __init__(self, config: SegmentConfig = None):
        self.config = config or SegmentConfig()
        self.stats = {
            'total_frames': 0,
            'scene_changes': 0,
            'dynamic_segments': 0,
            'discarded_short': 0,
            'discarded_static': 0,
            'ssim_gpu_count': 0,      # GPU로 계산한 SSIM 횟수
            'ssim_cpu_count': 0,      # CPU로 계산한 SSIM 횟수
            'ssim_gpu_time': 0.0,     # GPU SSIM 총 시간 (초)
            'ssim_cpu_time': 0.0,     # CPU SSIM 총 시간 (초)
        }

        # GPU 사용 가능 여부 확인
        self.gpu_available = False
        self.device = None
        if self.config.use_gpu:
            self.gpu_available = self._check_gpu_available()

    def _check_gpu_available(self) -> bool:
        """
        GPU 사용 가능 여부 확인 (CUDA/PyTorch)

        Returns:
            bool: GPU 사용 가능하면 True
        """
        try:
            # 1. PyTorch 설치 경로를 sys.path에 추가
            import sys
            from pathlib import Path
            import os

            # src/utils 경로 추가 (PyTorchInstaller import용)
            if getattr(sys, 'frozen', False):
                # PyInstaller 패키징 환경
                utils_dir = Path(sys.executable).parent / "_internal" / "src"
            else:
                # 개발 환경
                script_dir = Path(__file__).parent.parent
                utils_dir = script_dir / "src"

            if utils_dir.exists() and str(utils_dir) not in sys.path:
                sys.path.insert(0, str(utils_dir))

            # 2. PyTorch 설치 확인
            try:
                from utils.pytorch_installer import PyTorchInstaller
                installer = PyTorchInstaller.get_instance()

                if not installer.is_pytorch_installed():
                    print("⚠️ PyTorch가 설치되지 않았습니다. CPU 모드로 실행합니다.")
                    print("   GPU 가속을 사용하려면 GUI에서 'GPU 가속' 체크박스를 활성화하세요.")
                    return False

                # sys.path에 PyTorch 경로 추가
                installer.add_to_path()

            except ImportError:
                # PyTorchInstaller를 찾을 수 없는 경우 (이전 버전 호환성)
                print("⚠️ PyTorchInstaller를 찾을 수 없습니다. 시스템 PyTorch를 사용합니다.")

            # 3. PyTorch import 시도
            import torch

            if torch.cuda.is_available():
                self.device = torch.device('cuda')
                gpu_name = torch.cuda.get_device_name(0)
                print(f"✅ GPU 감지됨: {gpu_name}")

                # 4. 실제 GPU 텐서 생성 및 연산 테스트
                print("🔍 GPU 초기화 테스트 중...")
                try:
                    # 작은 행렬 곱셈으로 GPU 작동 확인
                    test_tensor = torch.randn(100, 100, device=self.device)
                    result = test_tensor @ test_tensor.T
                    torch.cuda.synchronize()  # GPU 작업 완료 대기

                    # 메모리 정보 확인
                    memory_allocated = torch.cuda.memory_allocated(0) / 1024 / 1024  # MB
                    memory_reserved = torch.cuda.memory_reserved(0) / 1024 / 1024    # MB

                    print(f"✅ GPU 가속 활성화 성공!")
                    print(f"   - GPU 메모리 할당: {memory_allocated:.1f} MB")
                    print(f"   - GPU 메모리 예약: {memory_reserved:.1f} MB")
                    return True

                except RuntimeError as e:
                    print(f"❌ GPU 텐서 생성 실패: {e}")
                    print("   CPU 모드로 실행합니다.")
                    return False
                except Exception as e:
                    print(f"❌ GPU 초기화 테스트 실패: {e}")
                    print("   CPU 모드로 실행합니다.")
                    return False
            else:
                print("⚠️ CUDA를 사용할 수 없습니다. CPU 모드로 실행합니다.")
                return False

        except ImportError:
            print("⚠️ PyTorch가 설치되지 않았습니다. CPU 모드로 실행합니다.")
            print("   GPU 가속을 사용하려면 GUI에서 'GPU 가속' 체크박스를 활성화하세요.")
            return False
        except (OSError, RuntimeError) as e:
            # DLL 로딩 실패 또는 CUDA 초기화 오류
            print(f"⚠️ PyTorch 로딩 실패: {e}")
            print("   CPU 모드로 실행합니다.")
            print("   해결 방법:")
            print("   1. GUI에서 'GPU 가속' 체크박스를 다시 활성화하세요.")
            print("   2. PyTorch 재설치: 설정 메뉴에서 'PyTorch 재설치' 클릭")
            return False
        except Exception as e:
            # 기타 모든 예외
            print(f"⚠️ GPU 초기화 중 예상치 못한 오류: {e}")
            print("   CPU 모드로 실행합니다.")
            return False

    def calculate_ssim(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """
        두 이미지 간 SSIM 계산 (CPU 또는 GPU)

        성능 최적화: config.ssim_scale < 1.0이면 해상도 축소 후 계산
        (segment 구간 결정에만 사용, 출력은 원본 해상도 유지)
        """
        import time

        # 해상도 축소 (설정된 경우)
        if self.config.ssim_scale < 1.0:
            h, w = img1.shape[:2]
            new_h = int(h * self.config.ssim_scale)
            new_w = int(w * self.config.ssim_scale)
            img1 = cv2.resize(img1, (new_w, new_h), interpolation=cv2.INTER_AREA)
            img2 = cv2.resize(img2, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # GPU 가속 사용 (PyTorch 사용 가능 시)
        if self.gpu_available:
            try:
                start_time = time.perf_counter()
                score = self._calculate_ssim_gpu(img1, img2)
                elapsed = time.perf_counter() - start_time

                self.stats['ssim_gpu_count'] += 1
                self.stats['ssim_gpu_time'] += elapsed
                return score
            except (OSError, RuntimeError, Exception) as e:
                # GPU 계산 실패 시 CPU로 자동 폴백
                print(f"⚠️ GPU SSIM 계산 실패, CPU로 전환: {e}")
                self.gpu_available = False  # 이후 모든 계산은 CPU 사용

        # CPU 버전 (기존 코드)
        start_time = time.perf_counter()
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        score, _ = ssim(gray1, gray2, full=True)
        elapsed = time.perf_counter() - start_time

        self.stats['ssim_cpu_count'] += 1
        self.stats['ssim_cpu_time'] += elapsed
        return score

    def _calculate_ssim_gpu_batch(self, frame_pairs: list) -> list:
        """
        GPU를 사용한 배치 SSIM 계산 (PyTorch) - 성능 최적화

        Args:
            frame_pairs: [(img1, img2), ...] 프레임 쌍 리스트

        Returns:
            SSIM 점수 리스트
        """
        try:
            import torch
            import torch.nn.functional as F

            if not frame_pairs:
                return []

            batch_size = len(frame_pairs)

            # BGR to Grayscale (CPU에서 배치 처리)
            gray1_list = []
            gray2_list = []

            for img1, img2 in frame_pairs:
                gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
                gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
                gray1_list.append(gray1)
                gray2_list.append(gray2)

            # NumPy to Torch Tensor (배치)
            gray1_batch = np.stack(gray1_list)
            gray2_batch = np.stack(gray2_list)

            t1 = torch.from_numpy(gray1_batch).float().unsqueeze(1).to(self.device) / 255.0
            t2 = torch.from_numpy(gray2_batch).float().unsqueeze(1).to(self.device) / 255.0

            # SSIM 계산 (배치)
            C1 = 0.01 ** 2
            C2 = 0.03 ** 2

            mu1 = F.avg_pool2d(t1, 11, 1, 5)
            mu2 = F.avg_pool2d(t2, 11, 1, 5)

            mu1_sq = mu1 ** 2
            mu2_sq = mu2 ** 2
            mu1_mu2 = mu1 * mu2

            sigma1_sq = F.avg_pool2d(t1 ** 2, 11, 1, 5) - mu1_sq
            sigma2_sq = F.avg_pool2d(t2 ** 2, 11, 1, 5) - mu2_sq
            sigma12 = F.avg_pool2d(t1 * t2, 11, 1, 5) - mu1_mu2

            ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / \
                       ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))

            # 배치별 평균 SSIM 점수
            scores = ssim_map.mean(dim=(1, 2, 3)).cpu().tolist()
            return scores

        except Exception as e:
            # GPU 오류 시 CPU로 폴백 (단일 프레임 처리)
            print(f"⚠️ GPU 배치 SSIM 계산 실패, CPU로 폴백: {e}")
            scores = []
            for img1, img2 in frame_pairs:
                gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
                gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
                score, _ = ssim(gray1, gray2, full=True)
                scores.append(score)
            return scores

    def _calculate_ssim_gpu(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """
        GPU를 사용한 SSIM 계산 (PyTorch)

        Args:
            img1: 첫 번째 이미지 (BGR)
            img2: 두 번째 이미지 (BGR)

        Returns:
            SSIM 점수
        """
        try:
            import torch
            import torch.nn.functional as F

            # BGR to Grayscale
            gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

            # NumPy to Torch Tensor
            t1 = torch.from_numpy(gray1).float().unsqueeze(0).unsqueeze(0).to(self.device) / 255.0
            t2 = torch.from_numpy(gray2).float().unsqueeze(0).unsqueeze(0).to(self.device) / 255.0

            # SSIM 계산 (간단한 버전)
            C1 = 0.01 ** 2
            C2 = 0.03 ** 2

            mu1 = F.avg_pool2d(t1, 11, 1, 5)
            mu2 = F.avg_pool2d(t2, 11, 1, 5)

            mu1_sq = mu1 ** 2
            mu2_sq = mu2 ** 2
            mu1_mu2 = mu1 * mu2

            sigma1_sq = F.avg_pool2d(t1 ** 2, 11, 1, 5) - mu1_sq
            sigma2_sq = F.avg_pool2d(t2 ** 2, 11, 1, 5) - mu2_sq
            sigma12 = F.avg_pool2d(t1 * t2, 11, 1, 5) - mu1_mu2

            ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / \
                       ((mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2))

            score = ssim_map.mean().item()
            return score

        except Exception as e:
            # GPU 오류 시 CPU로 폴백
            print(f"⚠️ GPU SSIM 계산 실패, CPU로 폴백: {e}")
            gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
            score, _ = ssim(gray1, gray2, full=True)
            return score

    def detect_segments(
        self,
        video_path: Path,
        progress_callback=None
    ) -> List[VideoSegment]:
        """
        비디오에서 동적인 세그먼트 탐지 (정적인 '잠수 구간'만 제외)

        Args:
            video_path: 입력 비디오 경로
            progress_callback: 진행 상황 콜백 함수(current, total)

        Returns:
            VideoSegment 리스트
        """
        return self._detect_segments_single(video_path, progress_callback)

    def _detect_segments_single(
        self,
        video_path: Path,
        progress_callback=None
    ) -> List[VideoSegment]:
        """
        싱글 프로세스 세그먼트 탐지

        Args:
            video_path: 입력 비디오 경로
            progress_callback: 진행 상황 콜백 함수(current, total)

        Returns:
            VideoSegment 리스트
        """
        # 비디오 리더 (OpenCV 또는 PyAV)
        cap = None
        using_pyav = False

        # 1단계: OpenCV로 열기 시도
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"비디오를 열 수 없습니다: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.stats['total_frames'] = total_frames

        print(f"📹 비디오 분석 중...")
        print(f"   - FPS: {fps:.2f}")
        print(f"   - 총 프레임: {total_frames:,}개")
        print(f"   - 길이: {total_frames / fps / 60:.1f}분")
        if self.config.ssim_scale < 1.0:
            print(f"   - SSIM 해상도 스케일: {self.config.ssim_scale:.2f} (성능 최적화 적용, 출력은 원본 유지)")
        if self.config.frame_skip > 1:
            print(f"   - 프레임 스킵: {self.config.frame_skip} (빠른 모드, ~{self.config.frame_skip}배 속도 향상)")

        segments = []
        current_segment_start = 0
        dynamic_frame_count = 0
        ssim_buffer = []

        # 첫 프레임 읽기 시도
        ret, prev_frame = cap.read()
        if not ret:
            # 2단계: OpenCV 실패 시 PyAV로 전환
            print("⚠️ OpenCV로 첫 프레임을 읽을 수 없습니다.")
            print("   비디오 코덱이 OpenCV와 호환되지 않을 수 있습니다.")
            print("🔄 PyAV로 전환을 시도합니다...")
            cap.release()

            # PyAV로 열기
            cap = PyAVVideoReader(video_path)
            if not cap.open():
                raise RuntimeError(
                    "첫 프레임을 읽을 수 없습니다.\n"
                    "비디오 파일이 손상되었거나 PyAV가 설치되지 않았습니다.\n"
                    "PyAV 설치: pip install av"
                )

            # PyAV에서 정보 가져오기
            fps = cap.fps
            total_frames = cap.total_frames
            self.stats['total_frames'] = total_frames
            using_pyav = True

            # 첫 프레임 다시 읽기
            ret, prev_frame = cap.read()
            if not ret:
                cap.release()
                raise RuntimeError("PyAV로도 첫 프레임을 읽을 수 없습니다")

        frame_idx = 0

        # Progress update 시간 기반 제어
        import time
        last_update_time = time.time()
        UPDATE_INTERVAL = 0.1  # 0.1초(100ms)마다 업데이트

        # GPU 배치 처리 설정
        BATCH_SIZE = 32  # GPU 메모리에 따라 조정 가능
        frame_batch = []  # [(prev_frame, current_frame), ...]
        frame_indices = []  # 각 배치 프레임의 인덱스

        use_batch_processing = (self.device and self.device.type == 'cuda')

        if use_batch_processing:
            print(f"🚀 GPU 배치 처리 모드 (배치 크기: {BATCH_SIZE})")

        while True:
            # 프레임 스킵 적용
            for _ in range(self.config.frame_skip - 1):
                ret = cap.grab()  # 프레임 읽지 않고 건너뛰기
                if not ret:
                    break
                frame_idx += 1

            ret, current_frame = cap.read()
            if not ret:
                break

            frame_idx += 1

            # 시간 기반 진행률 업데이트 (0.1초마다)
            current_time = time.time()
            if progress_callback and (current_time - last_update_time >= UPDATE_INTERVAL):
                progress_callback(frame_idx, total_frames)
                last_update_time = current_time

            # 배치 처리 모드
            if use_batch_processing:
                # 배치에 프레임 추가
                frame_batch.append((prev_frame.copy(), current_frame.copy()))
                frame_indices.append(frame_idx)

                # 배치가 가득 차면 처리
                if len(frame_batch) >= BATCH_SIZE:
                    try:
                        # GPU 배치 SSIM 계산
                        ssim_scores = self._calculate_ssim_gpu_batch(frame_batch)

                        # 결과 처리
                        for batch_idx, ssim_score in enumerate(ssim_scores):
                            ssim_buffer.append(ssim_score)

                            # 장면 전환 감지 처리 (아래에서 통합)
                            batch_frame_idx = frame_indices[batch_idx]
                            if ssim_score < self.config.scene_change_threshold:
                                self.stats['scene_changes'] += 1

                                if dynamic_frame_count >= self.config.min_dynamic_frames:
                                    segment = self._create_segment(
                                        current_segment_start,
                                        batch_frame_idx - 1,
                                        fps,
                                        ssim_buffer[:-1]
                                    )

                                    if self._is_valid_segment(segment):
                                        segments.append(segment)
                                        self.stats['dynamic_segments'] += 1
                                    else:
                                        if segment.duration < self.config.min_duration:
                                            self.stats['discarded_short'] += 1
                                        elif segment.avg_ssim >= self.config.static_threshold:
                                            self.stats['discarded_static'] += 1

                                current_segment_start = batch_frame_idx
                                dynamic_frame_count = 0
                                ssim_buffer = []
                            else:
                                dynamic_frame_count += 1

                        # 배치 초기화
                        frame_batch.clear()
                        frame_indices.clear()

                    except Exception as e:
                        # GPU 오류 처리 (OOM 등)
                        import torch
                        if isinstance(e, torch.cuda.OutOfMemoryError):
                            print(f"⚠️ GPU 메모리 부족, 배치 크기 {BATCH_SIZE} → {BATCH_SIZE // 2}로 감소")
                            BATCH_SIZE = max(1, BATCH_SIZE // 2)
                        else:
                            print(f"⚠️ GPU 배치 처리 오류: {e}")

                        # 현재 배치 단일 처리로 폴백
                        for i, (pf, cf) in enumerate(frame_batch):
                            ssim_score = self.calculate_ssim(pf, cf)
                            ssim_buffer.append(ssim_score)
                        frame_batch.clear()
                        frame_indices.clear()

                # prev_frame 업데이트 (배치 모드)
                prev_frame = current_frame
                continue  # 배치 모드에서는 아래 단일 처리 스킵

            # 단일 프레임 처리 모드 (CPU 또는 배치 미사용)
            ssim_score = self.calculate_ssim(prev_frame, current_frame)
            ssim_buffer.append(ssim_score)

            # 장면 전환 감지 (scene_threshold 이하)
            if ssim_score < self.config.scene_change_threshold:
                self.stats['scene_changes'] += 1

                # 이전 세그먼트 저장 (조건 충족 시)
                if dynamic_frame_count >= self.config.min_dynamic_frames:
                    segment = self._create_segment(
                        current_segment_start,
                        frame_idx - 1,
                        fps,
                        ssim_buffer[:-1]
                    )

                    if self._is_valid_segment(segment):
                        segments.append(segment)
                        self.stats['dynamic_segments'] += 1
                    else:
                        if segment.duration < self.config.min_duration:
                            self.stats['discarded_short'] += 1
                        elif segment.avg_ssim >= self.config.static_threshold:
                            self.stats['discarded_static'] += 1

                # 새 세그먼트 시작
                current_segment_start = frame_idx
                dynamic_frame_count = 0
                ssim_buffer = []

            # 동적 구간 카운트 (static_threshold 미만이면 모두 동적)
            elif ssim_score < self.config.static_threshold:
                dynamic_frame_count += 1

            # 최대 길이 초과 시 세그먼트 분할
            segment_frames = frame_idx - current_segment_start
            segment_duration = segment_frames / fps

            if segment_duration >= self.config.max_duration:
                if dynamic_frame_count >= self.config.min_dynamic_frames:
                    segment = self._create_segment(
                        current_segment_start,
                        frame_idx,
                        fps,
                        ssim_buffer
                    )

                    if self._is_valid_segment(segment):
                        segments.append(segment)
                        self.stats['dynamic_segments'] += 1

                current_segment_start = frame_idx
                dynamic_frame_count = 0
                ssim_buffer = []

            # 최대 세그먼트 수 도달
            if (self.config.max_segments and
                len(segments) >= self.config.max_segments):
                print(f"\n⚠️ 최대 세그먼트 수({self.config.max_segments})에 도달했습니다.")
                break

            prev_frame = current_frame

        # 배치 모드에서 남은 프레임 처리
        if use_batch_processing and len(frame_batch) > 0:
            try:
                import torch
                ssim_scores = self._calculate_ssim_gpu_batch(frame_batch)

                for batch_idx, ssim_score in enumerate(ssim_scores):
                    ssim_buffer.append(ssim_score)

                    batch_frame_idx = frame_indices[batch_idx]
                    if ssim_score < self.config.scene_change_threshold:
                        self.stats['scene_changes'] += 1

                        if dynamic_frame_count >= self.config.min_dynamic_frames:
                            segment = self._create_segment(
                                current_segment_start,
                                batch_frame_idx - 1,
                                fps,
                                ssim_buffer[:-1]
                            )

                            if self._is_valid_segment(segment):
                                segments.append(segment)
                                self.stats['dynamic_segments'] += 1

                        current_segment_start = batch_frame_idx
                        dynamic_frame_count = 0
                        ssim_buffer = []
                    else:
                        dynamic_frame_count += 1

            except Exception as e:
                print(f"⚠️ 남은 배치 처리 실패: {e}")

        # 마지막 세그먼트 처리
        if dynamic_frame_count >= self.config.min_dynamic_frames:
            segment = self._create_segment(
                current_segment_start,
                frame_idx,
                fps,
                ssim_buffer
            )

            if self._is_valid_segment(segment):
                segments.append(segment)
                self.stats['dynamic_segments'] += 1

        cap.release()

        print(f"\n✅ 세그먼트 탐지 완료!")
        self._print_stats()

        return segments

    def _create_segment(
        self,
        start_frame: int,
        end_frame: int,
        fps: float,
        ssim_scores: List[float]
    ) -> VideoSegment:
        """세그먼트 객체 생성"""
        start_time = start_frame / fps
        end_time = end_frame / fps
        duration = end_time - start_time
        avg_ssim = np.mean(ssim_scores) if ssim_scores else 0.0

        return VideoSegment(
            start_frame=start_frame,
            end_frame=end_frame,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            avg_ssim=avg_ssim
        )

    def _is_valid_segment(self, segment: VideoSegment) -> bool:
        """세그먼트 유효성 검증"""
        # 최소 길이 체크
        if segment.duration < self.config.min_duration:
            return False

        # 정적 구간 체크 (평균 SSIM이 static_threshold 이상이면 제외)
        if segment.avg_ssim >= self.config.static_threshold:
            return False

        return True

    def export_segments(
        self,
        video_path: Path,
        segments: List[VideoSegment],
        output_dir: Path,
        progress_callback=None
    ) -> List[Path]:
        """
        세그먼트를 개별 비디오 파일로 저장 (ffmpeg 사용)

        Args:
            video_path: 원본 비디오 경로
            segments: 세그먼트 리스트
            output_dir: 출력 디렉토리
            progress_callback: 진행 상황 콜백

        Returns:
            저장된 비디오 파일 경로 리스트
        """
        # ffmpeg 확인 및 자동 설치
        if not check_and_install_ffmpeg():
            raise RuntimeError(
                "ffmpeg를 사용할 수 없습니다. "
                "터미널을 재시작하거나 수동으로 설치해주세요."
            )

        output_dir.mkdir(parents=True, exist_ok=True)

        saved_paths = []

        print(f"\n🎬 세그먼트 비디오 생성 중 (ffmpeg)...")

        for idx, segment in enumerate(segments):
            output_path = output_dir / f"segment_{idx+1:03d}.mp4"

            # ffmpeg로 비디오 자르기 (재인코딩 없이 빠르게)
            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-ss', str(segment.start_time),
                '-to', str(segment.end_time),
                '-c', 'copy',
                '-y',  # 덮어쓰기
                str(output_path)
            ]

            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                saved_paths.append(output_path)

                if progress_callback:
                    progress_callback(idx + 1, len(segments))

                print(f"   ✓ segment_{idx+1:03d}.mp4 ({segment.duration:.1f}초, "
                      f"SSIM: {segment.avg_ssim:.3f})")
            except subprocess.CalledProcessError as e:
                print(f"   ⚠️ segment_{idx+1:03d}.mp4 생성 실패: {e.stderr}")

        # 채택되지 않은 구간 저장 (실험 기능)
        if self.config.save_discarded:
            self._export_discarded_segments(video_path, segments, output_dir)

        print(f"\n✅ {len(saved_paths)}개 세그먼트 저장 완료!")
        return saved_paths

    def _export_discarded_segments(
        self,
        video_path: Path,
        accepted_segments: List[VideoSegment],
        output_dir: Path
    ):
        """
        채택되지 않은 구간을 else 폴더에 저장

        Args:
            video_path: 원본 비디오 경로
            accepted_segments: 채택된 세그먼트 리스트
            output_dir: 출력 디렉토리
        """
        # ffmpeg 확인 (이미 export_segments에서 체크했으므로 재확인만)
        if not check_and_install_ffmpeg():
            print("⚠️ ffmpeg를 사용할 수 없어 채택되지 않은 구간 저장을 건너뜁니다.")
            return

        # else 폴더 생성
        else_dir = output_dir / "else"
        else_dir.mkdir(exist_ok=True)

        # 비디오 총 길이 가져오기
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        total_duration = total_frames / fps
        cap.release()

        print(f"\n📦 채택되지 않은 구간 저장 중...")

        # 채택된 구간을 시간 순으로 정렬
        sorted_segments = sorted(accepted_segments, key=lambda s: s.start_time)

        # 빈 구간 찾기
        discarded_segments = []
        prev_end_time = 0.0

        for segment in sorted_segments:
            if segment.start_time > prev_end_time + 0.1:  # 0.1초 이상 공백
                discarded_segments.append((prev_end_time, segment.start_time))
            prev_end_time = segment.end_time

        # 마지막 구간 이후
        if prev_end_time < total_duration - 0.1:
            discarded_segments.append((prev_end_time, total_duration))

        # 빈 구간 저장
        for idx, (start_time, end_time) in enumerate(discarded_segments):
            output_path = else_dir / f"discarded_{idx+1:03d}.mp4"
            duration = end_time - start_time

            cmd = [
                'ffmpeg',
                '-i', str(video_path),
                '-ss', str(start_time),
                '-to', str(end_time),
                '-c', 'copy',
                '-y',
                str(output_path)
            ]

            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                print(f"   ✓ discarded_{idx+1:03d}.mp4 ({duration:.1f}초)")
            except subprocess.CalledProcessError as e:
                print(f"   ⚠️ discarded_{idx+1:03d}.mp4 생성 실패: {e.stderr}")

        print(f"✅ {len(discarded_segments)}개 채택되지 않은 구간 저장 완료!")

    def save_metadata(
        self,
        output_dir: Path,
        video_path: Path,
        segments: List[VideoSegment]
    ):
        """메타데이터 저장"""
        metadata = {
            'source_video': str(video_path),
            'timestamp': datetime.now().isoformat(),
            'config': {
                'scene_change_threshold': self.config.scene_change_threshold,
                'static_threshold': self.config.static_threshold,
                'min_duration': self.config.min_duration,
                'max_duration': self.config.max_duration,
                'ssim_scale': self.config.ssim_scale,
                'frame_skip': self.config.frame_skip,
                'use_gpu': self.config.use_gpu,
            },
            'stats': self.stats,
            'segments': [
                {
                    'index': i + 1,
                    'filename': f"segment_{i+1:03d}.mp4",
                    'start_frame': seg.start_frame,
                    'end_frame': seg.end_frame,
                    'start_time': seg.start_time,
                    'end_time': seg.end_time,
                    'duration': seg.duration,
                    'avg_ssim': seg.avg_ssim
                }
                for i, seg in enumerate(segments)
            ]
        }

        metadata_path = output_dir / "segments_metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        print(f"\n💾 메타데이터 저장: {metadata_path}")

    def _print_stats(self):
        """통계 출력"""
        print(f"\n📊 세그멘테이션 통계:")
        print(f"   - 총 프레임: {self.stats['total_frames']:,}개")
        print(f"   - 장면 전환: {self.stats['scene_changes']:,}개")
        print(f"   - 동적 세그먼트: {self.stats['dynamic_segments']:,}개")
        print(f"   - 제외 (짧음): {self.stats['discarded_short']:,}개")
        print(f"   - 제외 (정적/잠수): {self.stats['discarded_static']:,}개")

        # SSIM 성능 통계
        gpu_count = self.stats['ssim_gpu_count']
        cpu_count = self.stats['ssim_cpu_count']
        gpu_time = self.stats['ssim_gpu_time']
        cpu_time = self.stats['ssim_cpu_time']

        if gpu_count > 0 or cpu_count > 0:
            print(f"\n⚡ SSIM 성능 통계:")
            if gpu_count > 0:
                avg_gpu_time = (gpu_time / gpu_count) * 1000  # ms
                print(f"   - GPU SSIM: {gpu_count:,}회, 평균 {avg_gpu_time:.2f}ms/프레임, 총 {gpu_time:.2f}초")
            if cpu_count > 0:
                avg_cpu_time = (cpu_time / cpu_count) * 1000  # ms
                print(f"   - CPU SSIM: {cpu_count:,}회, 평균 {avg_cpu_time:.2f}ms/프레임, 총 {cpu_time:.2f}초")
            if gpu_count > 0 and cpu_count > 0:
                speedup = (cpu_time / cpu_count) / (gpu_time / gpu_count)
                print(f"   - GPU 가속 배율: {speedup:.1f}x")


def main():
    parser = argparse.ArgumentParser(
        description="SSIM 기반 스마트 비디오 세그멘테이션"
    )
    parser.add_argument(
        '--input',
        type=Path,
        required=True,
        help="입력 비디오 경로"
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help="출력 디렉토리"
    )
    parser.add_argument(
        '--scene-threshold',
        type=float,
        default=0.3,
        help="장면 전환 임계값 (기본: 0.3)"
    )
    parser.add_argument(
        '--static-threshold',
        type=float,
        default=0.95,
        help="정적 구간 임계값 - 이보다 높으면 잠수 구간으로 제외 (기본: 0.95)"
    )
    parser.add_argument(
        '--min-duration',
        type=float,
        default=5.0,
        help="최소 세그먼트 길이 초 (기본: 5.0)"
    )
    parser.add_argument(
        '--max-duration',
        type=float,
        default=60.0,
        help="최대 세그먼트 길이 초 (기본: 60.0)"
    )
    parser.add_argument(
        '--max-segments',
        type=int,
        default=None,
        help="최대 세그먼트 수 (기본: 무제한)"
    )
    parser.add_argument(
        '--ssim-scale',
        type=float,
        default=1.0,
        help="SSIM 계산 시 해상도 스케일 (0.25=4배 빠름, 1.0=원본, 기본: 1.0, 출력은 항상 원본 해상도)"
    )
    parser.add_argument(
        '--frame-skip',
        type=int,
        default=1,
        help="프레임 스킵 (1=모든 프레임, 3=3프레임마다, 기본: 1)"
    )
    parser.add_argument(
        '--save-discarded',
        action='store_true',
        help="채택되지 않은 구간도 else 폴더에 저장 (실험 기능)"
    )
    parser.add_argument(
        '--use-gpu',
        action='store_true',
        help="GPU 가속 사용 (CUDA 사용 가능 시)"
    )

    args = parser.parse_args()

    # 설정 생성
    config = SegmentConfig(
        scene_change_threshold=args.scene_threshold,
        static_threshold=args.static_threshold,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        max_segments=args.max_segments,
        ssim_scale=args.ssim_scale,
        frame_skip=args.frame_skip,
        save_discarded=args.save_discarded,
        use_gpu=args.use_gpu
    )

    # 세그멘터 생성
    segmenter = VideoSegmenter(config)

    # 진행 상황 콜백
    def progress_callback(current, total):
        print(f"   진행: {current:,} / {total:,} ({current / total * 100:.1f}%)", end='\r')

    try:
        # 세그먼트 탐지
        segments = segmenter.detect_segments(args.input, progress_callback)

        if not segments:
            print("\n❌ 유효한 세그먼트를 찾을 수 없습니다.")
            return 1

        # 세그먼트 비디오 생성
        saved_paths = segmenter.export_segments(
            args.input,
            segments,
            args.output,
            progress_callback
        )

        # 메타데이터 저장
        segmenter.save_metadata(args.output, args.input, segments)

        print(f"\n✅ 완료!")
        print(f"   출력 디렉토리: {args.output}")
        print(f"   세그먼트 수: {len(saved_paths)}개")

        total_duration = sum(seg.duration for seg in segments)
        print(f"   총 길이: {total_duration / 60:.1f}분")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
