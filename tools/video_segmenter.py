#!/usr/bin/env python3
"""
Optical Flow 기반 스마트 비디오 세그멘테이션
게임 영상을 움직임 패턴에 따라 분할하여 YOLO 학습 데이터 최적화

커팅 전략:
- 움직임 적은 구간: 버림 (오버피팅 방지)
- 장면 전환 구간: 우선 선택 (컨텐츠 입장/종료 감지)
- UI 고정 + 배경 동적 구간: 적당량 선택 (UI 추적 학습)

사용법:
    python tools/video_segmenter.py --input datasets/raw/gameplay.mp4 \
                                     --output datasets/clips/ \
                                     --motion-low 2.0 \
                                     --motion-high 15.0 \
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
import subprocess
import shutil
import sys
import os


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
    avg_motion: float  # 구간 내 평균 움직임 크기
    avg_scene_change: float  # 구간 내 평균 장면 전환 점수
    priority: int  # 우선순위 (1=장면전환, 2=중간동적, 3=저동적)


@dataclass
class SegmentConfig:
    """세그멘테이션 설정"""
    # Optical Flow 기반 움직임 감지
    motion_low_threshold: float = 2.0    # 이보다 낮으면 저동적 구간 (버림)
    motion_high_threshold: float = 15.0  # 이보다 높으면 과도한 움직임 (제외)

    # 장면 전환 감지 (히스토그램 차이)
    scene_change_threshold: float = 0.5  # 히스토그램 차이가 이보다 크면 장면 전환
    scene_change_important: float = 0.5  # 장면 전환 점수가 이보다 높으면 우선 선택

    # 세그먼트 분류 기준
    min_dynamic_frames: int = 30         # 최소 동적 프레임 수 (1초@30fps)

    # 세그먼트 제약
    min_duration: float = 5.0            # 최소 세그먼트 길이 (초)
    max_duration: float = 60.0           # 최대 세그먼트 길이 (초)
    max_segments: Optional[int] = None   # 최대 세그먼트 수

    # 우선순위 기반 선택
    priority_ratios: dict = None         # {1: 비율, 2: 비율, 3: 비율} 예: {1: 0.4, 2: 0.5, 3: 0.1}

    # 성능 최적화
    flow_scale: float = 0.5              # Optical Flow 계산 시 해상도 스케일 (0.5 = 2배 빠름)
    frame_skip: int = 1                  # 프레임 스킵 (1=모든 프레임, 3=3프레임마다)
    use_gpu: bool = False                # GPU 가속 사용 (CUDA 사용 가능 시)

    # 실험 기능
    save_discarded: bool = False         # 채택되지 않은 구간도 별도 저장

    # 출력 설정
    output_codec: str = "mp4v"           # 출력 코덱
    output_fps: Optional[int] = None     # 출력 FPS (None이면 원본)

    def __post_init__(self):
        if self.priority_ratios is None:
            self.priority_ratios = {1: 0.4, 2: 0.5, 3: 0.1}  # 기본값


class VideoSegmenter:
    """Optical Flow 기반 비디오 세그멘테이션"""

    def __init__(self, config: SegmentConfig = None):
        self.config = config or SegmentConfig()
        self.stats = {
            'total_frames': 0,
            'scene_changes': 0,
            'priority_1_segments': 0,  # 장면 전환 포함 세그먼트
            'priority_2_segments': 0,  # 중간 동적 세그먼트
            'priority_3_segments': 0,  # 저동적 세그먼트
            'discarded_short': 0,
            'discarded_low_motion': 0,
            'flow_gpu_count': 0,       # GPU로 계산한 Optical Flow 횟수
            'flow_cpu_count': 0,       # CPU로 계산한 Optical Flow 횟수
            'flow_gpu_time': 0.0,      # GPU Flow 총 시간 (초)
            'flow_cpu_time': 0.0,      # CPU Flow 총 시간 (초)
        }

        # GPU 사용 가능 여부 확인
        self.gpu_available = False
        self.device = None
        self.sobel_x = None  # Sobel X 필터 (재사용)
        self.sobel_y = None  # Sobel Y 필터 (재사용)
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

                    # Sobel 필터 미리 생성 (GPU 메모리에 상주)
                    self.sobel_x = torch.tensor([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]],
                                               dtype=torch.float32, device=self.device).view(1, 1, 3, 3)
                    self.sobel_y = torch.tensor([[-1, -2, -1], [0, 0, 0], [1, 2, 1]],
                                               dtype=torch.float32, device=self.device).view(1, 1, 3, 3)
                    print("✅ GPU Sobel 필터 초기화 완료")

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

    def calculate_motion_and_scene_change(
        self,
        prev_frame: np.ndarray,
        current_frame: np.ndarray
    ) -> Tuple[float, float]:
        """
        Optical Flow 기반 움직임 크기 + 히스토그램 기반 장면 전환 점수 계산

        Returns:
            (motion_score, scene_change_score)
            - motion_score: 평균 optical flow 크기 (픽셀/프레임)
            - scene_change_score: 히스토그램 차이 (0~1, 1이 완전히 다름)
        """
        import time

        # 해상도 축소 (설정된 경우)
        if self.config.flow_scale < 1.0:
            h, w = prev_frame.shape[:2]
            new_h = int(h * self.config.flow_scale)
            new_w = int(w * self.config.flow_scale)
            prev_small = cv2.resize(prev_frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
            curr_small = cv2.resize(current_frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            prev_small = prev_frame
            curr_small = current_frame

        # GPU 가속 사용 (PyTorch + CUDA Optical Flow)
        if self.gpu_available:
            try:
                start_time = time.perf_counter()
                motion_score, scene_change_score = self._calculate_flow_gpu(prev_small, curr_small)
                elapsed = time.perf_counter() - start_time

                self.stats['flow_gpu_count'] += 1
                self.stats['flow_gpu_time'] += elapsed
                return motion_score, scene_change_score
            except (OSError, RuntimeError, Exception) as e:
                print(f"⚠️ GPU Optical Flow 계산 실패, CPU로 전환: {e}")
                self.gpu_available = False

        # CPU 버전 (OpenCV Farneback)
        start_time = time.perf_counter()

        # 1. Optical Flow 계산
        prev_gray = cv2.cvtColor(prev_small, cv2.COLOR_BGR2GRAY)
        curr_gray = cv2.cvtColor(curr_small, cv2.COLOR_BGR2GRAY)

        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, curr_gray,
            None,
            pyr_scale=0.5,
            levels=3,
            winsize=15,
            iterations=3,
            poly_n=5,
            poly_sigma=1.2,
            flags=0
        )

        # 움직임 크기 (magnitude)
        magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
        motion_score = np.mean(magnitude)

        # 2. 히스토그램 기반 장면 전환 감지
        hist_prev = cv2.calcHist([prev_small], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
        hist_curr = cv2.calcHist([curr_small], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])

        hist_prev = cv2.normalize(hist_prev, hist_prev).flatten()
        hist_curr = cv2.normalize(hist_curr, hist_curr).flatten()

        # Correlation 기반 유사도 (1 - correlation = 차이)
        scene_change_score = 1.0 - cv2.compareHist(hist_prev, hist_curr, cv2.HISTCMP_CORREL)

        elapsed = time.perf_counter() - start_time
        self.stats['flow_cpu_count'] += 1
        self.stats['flow_cpu_time'] += elapsed

        return motion_score, scene_change_score

    def _calculate_flow_gpu(
        self,
        prev_frame: np.ndarray,
        current_frame: np.ndarray
    ) -> Tuple[float, float]:
        """
        GPU를 사용한 Optical Flow + 히스토그램 계산 (PyTorch 완전 GPU 구현)

        Lucas-Kanade 방식의 간소화된 gradient-based optical flow를 사용합니다.
        CPU Farneback보다 정확도는 다소 낮지만 20-50배 빠릅니다.

        Args:
            prev_frame: 이전 프레임 (BGR)
            current_frame: 현재 프레임 (BGR)

        Returns:
            (motion_score, scene_change_score)
        """
        try:
            import torch
            import torch.nn.functional as F

            # BGR -> Grayscale 변환 (GPU에서)
            # 가중치: B=0.114, G=0.587, R=0.299
            prev_tensor = torch.from_numpy(prev_frame).float().to(self.device)
            curr_tensor = torch.from_numpy(current_frame).float().to(self.device)

            prev_gray = (prev_tensor[..., 0] * 0.114 +
                        prev_tensor[..., 1] * 0.587 +
                        prev_tensor[..., 2] * 0.299)
            curr_gray = (curr_tensor[..., 0] * 0.114 +
                        curr_tensor[..., 1] * 0.587 +
                        curr_tensor[..., 2] * 0.299)

            # Add batch and channel dimensions for conv2d: [H, W] -> [1, 1, H, W]
            prev_gray = prev_gray.unsqueeze(0).unsqueeze(0)
            curr_gray = curr_gray.unsqueeze(0).unsqueeze(0)

            # Spatial gradients (Ix, Iy) - 미리 생성된 Sobel 필터 사용
            Ix = F.conv2d(curr_gray, self.sobel_x, padding=1)
            Iy = F.conv2d(curr_gray, self.sobel_y, padding=1)

            # Temporal gradient (It)
            It = curr_gray - prev_gray

            # Lucas-Kanade 방정식: Ix*u + Iy*v + It = 0
            # 간소화된 추정: motion magnitude ≈ |It| / (|Ix| + |Iy| + epsilon)
            # 더 정확한 방법도 가능하지만 속도를 위해 단순화
            gradient_mag = torch.sqrt(Ix**2 + Iy**2) + 1e-6
            motion_magnitude = torch.abs(It) / gradient_mag

            # Motion score 계산
            motion_score = float(motion_magnitude.mean().cpu().item())

            # 히스토그램 기반 장면 전환 감지 (GPU)
            # 8x8x8 bins로 RGB 히스토그램 계산
            prev_rgb = prev_tensor / 32.0  # [0, 255] -> [0, 8) bins
            curr_rgb = curr_tensor / 32.0

            # Flatten spatial dimensions
            prev_flat = prev_rgb.view(-1, 3).long()
            curr_flat = curr_rgb.view(-1, 3).long()

            # Compute 3D histogram indices
            prev_indices = prev_flat[:, 0] * 64 + prev_flat[:, 1] * 8 + prev_flat[:, 2]
            curr_indices = curr_flat[:, 0] * 64 + curr_flat[:, 1] * 8 + curr_flat[:, 2]

            # Bincount (histogram)
            hist_prev = torch.bincount(prev_indices.clamp(0, 511), minlength=512).float()
            hist_curr = torch.bincount(curr_indices.clamp(0, 511), minlength=512).float()

            # Normalize
            hist_prev = hist_prev / (hist_prev.sum() + 1e-6)
            hist_curr = hist_curr / (hist_curr.sum() + 1e-6)

            # Correlation
            correlation = torch.sum(hist_prev * hist_curr) / (
                torch.sqrt(torch.sum(hist_prev**2)) * torch.sqrt(torch.sum(hist_curr**2)) + 1e-6
            )
            scene_change_score = float((1.0 - correlation).cpu().item())

            # GPU 메모리 즉시 해제
            del prev_tensor, curr_tensor, prev_gray, curr_gray
            del Ix, Iy, It, gradient_mag, motion_magnitude
            del prev_rgb, curr_rgb, prev_flat, curr_flat
            del prev_indices, curr_indices, hist_prev, hist_curr, correlation

            return motion_score, scene_change_score

        except Exception as e:
            # GPU 오류 시 CPU로 폴백
            print(f"⚠️ GPU Flow 계산 실패, CPU로 전환: {e}")
            self.gpu_available = False  # GPU 비활성화

            prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            curr_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)

            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, curr_gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0
            )

            magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
            motion_score = np.mean(magnitude)

            hist_prev = cv2.calcHist([prev_frame], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            hist_curr = cv2.calcHist([current_frame], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            hist_prev = cv2.normalize(hist_prev, hist_prev).flatten()
            hist_curr = cv2.normalize(hist_curr, hist_curr).flatten()
            scene_change_score = 1.0 - cv2.compareHist(hist_prev, hist_curr, cv2.HISTCMP_CORREL)

            return motion_score, scene_change_score

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
        if self.config.flow_scale < 1.0:
            print(f"   - Optical Flow 해상도 스케일: {self.config.flow_scale:.2f} (성능 최적화 적용, 출력은 원본 유지)")
        if self.config.frame_skip > 1:
            print(f"   - 프레임 스킵: {self.config.frame_skip} (빠른 모드, ~{self.config.frame_skip}배 속도 향상)")

        segments = []
        current_segment_start = 0
        dynamic_frame_count = 0
        motion_buffer = []  # 움직임 점수 버퍼
        scene_change_buffer = []  # 장면 전환 점수 버퍼

        # 첫 프레임 읽기 시도
        ret, prev_frame = cap.read()
        if not ret:
            # 2단계: OpenCV 실패 시 PyAV로 전환
            print("⚠️ OpenCV로 첫 프레임을 읽을 수 없습니다.")
            print("   비디오 코덱이 OpenCV와 호환되지 않을 수 있습니다.")
            print("🔄 PyAV로 전환을 시도합니다...")
            print("   💡 아래 'Failed to decode frame' 경고는 PyAV 내부 로그이며 무시해도 됩니다.")
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

        # GPU 가속 경고
        if self.gpu_available:
            print(f"⚠️ 참고: Optical Flow는 CPU 전용이므로 GPU 가속 효과가 제한적입니다.")
            print(f"   (magnitude 계산만 GPU 사용, 전체의 ~5% 미만)")
            print(f"   더 빠른 처리를 원하시면 flow_scale을 낮추거나 frame_skip을 높이세요.")

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

            # Optical Flow + 히스토그램 기반 스코어 계산
            motion_score, scene_change_score = self.calculate_motion_and_scene_change(prev_frame, current_frame)
            motion_buffer.append(motion_score)
            scene_change_buffer.append(scene_change_score)

            # 장면 전환 감지 (scene_change_threshold 이상)
            if scene_change_score >= self.config.scene_change_threshold:
                self.stats['scene_changes'] += 1

                # 이전 세그먼트 저장 (조건 충족 시)
                if dynamic_frame_count >= self.config.min_dynamic_frames:
                    segment = self._create_segment(
                        current_segment_start,
                        frame_idx - 1,
                        fps,
                        motion_buffer[:-1],
                        scene_change_buffer[:-1]
                    )

                    if self._is_valid_segment(segment):
                        segments.append(segment)
                        # 우선순위별 카운팅
                        if segment.priority == 1:
                            self.stats['priority_1_segments'] += 1
                        elif segment.priority == 2:
                            self.stats['priority_2_segments'] += 1
                        else:
                            self.stats['priority_3_segments'] += 1
                    else:
                        if segment.duration < self.config.min_duration:
                            self.stats['discarded_short'] += 1
                        elif segment.avg_motion < self.config.motion_low_threshold:
                            self.stats['discarded_low_motion'] += 1

                # 새 세그먼트 시작
                current_segment_start = frame_idx
                dynamic_frame_count = 0
                motion_buffer = []
                scene_change_buffer = []

            # 동적 구간 카운트 (motion_low_threshold 이상이면 동적)
            elif motion_score >= self.config.motion_low_threshold:
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
                        motion_buffer,
                        scene_change_buffer
                    )

                    if self._is_valid_segment(segment):
                        segments.append(segment)
                        # 우선순위별 카운팅
                        if segment.priority == 1:
                            self.stats['priority_1_segments'] += 1
                        elif segment.priority == 2:
                            self.stats['priority_2_segments'] += 1
                        else:
                            self.stats['priority_3_segments'] += 1

                current_segment_start = frame_idx
                dynamic_frame_count = 0
                motion_buffer = []
                scene_change_buffer = []

            # 최대 세그먼트 수 도달
            if (self.config.max_segments and
                len(segments) >= self.config.max_segments):
                print(f"\n⚠️ 최대 세그먼트 수({self.config.max_segments})에 도달했습니다.")
                break

            prev_frame = current_frame

        # 마지막 세그먼트 처리
        if dynamic_frame_count >= self.config.min_dynamic_frames:
            segment = self._create_segment(
                current_segment_start,
                frame_idx,
                fps,
                motion_buffer,
                scene_change_buffer
            )

            if self._is_valid_segment(segment):
                segments.append(segment)
                # 우선순위별 카운팅
                if segment.priority == 1:
                    self.stats['priority_1_segments'] += 1
                elif segment.priority == 2:
                    self.stats['priority_2_segments'] += 1
                else:
                    self.stats['priority_3_segments'] += 1

        cap.release()

        # GPU 메모리 정리 (GPU 가속 사용 시)
        if self.gpu_available and self.device and self.device.type == 'cuda':
            try:
                import torch
                print(f"\n🧹 GPU 메모리 정리 중...")

                # 1. 캐시된 메모리 해제
                torch.cuda.empty_cache()

                # 2. GPU 작업 완료 대기
                torch.cuda.synchronize()

                # 3. 메모리 통계 출력
                memory_allocated = torch.cuda.memory_allocated(0) / 1024 / 1024  # MB
                memory_reserved = torch.cuda.memory_reserved(0) / 1024 / 1024    # MB

                print(f"   GPU 메모리 할당: {memory_allocated:.1f} MB")
                print(f"   GPU 메모리 예약: {memory_reserved:.1f} MB")
                print(f"   ✅ GPU 메모리 정리 완료")
            except Exception as e:
                print(f"   ⚠️ GPU 메모리 정리 실패 (무시됨): {e}")

        print(f"\n✅ 세그먼트 탐지 완료!")
        self._print_stats()

        return segments

    def _create_segment(
        self,
        start_frame: int,
        end_frame: int,
        fps: float,
        motion_scores: List[float],
        scene_change_scores: List[float]
    ) -> VideoSegment:
        """세그먼트 객체 생성 (우선순위 자동 계산)"""
        start_time = start_frame / fps
        end_time = end_frame / fps
        duration = end_time - start_time
        avg_motion = np.mean(motion_scores) if motion_scores else 0.0
        avg_scene_change = np.mean(scene_change_scores) if scene_change_scores else 0.0

        # 우선순위 결정
        # 1순위: 장면 전환 포함 구간
        if avg_scene_change >= self.config.scene_change_important:
            priority = 1
        # 2순위: 중간 동적 구간
        elif self.config.motion_low_threshold <= avg_motion <= self.config.motion_high_threshold:
            priority = 2
        # 3순위: 저동적 구간
        else:
            priority = 3

        return VideoSegment(
            start_frame=start_frame,
            end_frame=end_frame,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            avg_motion=avg_motion,
            avg_scene_change=avg_scene_change,
            priority=priority
        )

    def _is_valid_segment(self, segment: VideoSegment) -> bool:
        """세그먼트 유효성 검증"""
        # 최소 길이 체크
        if segment.duration < self.config.min_duration:
            return False

        # 저동적 구간 체크 (평균 motion이 motion_low_threshold 미만이면 제외)
        if segment.avg_motion < self.config.motion_low_threshold:
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
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                saved_paths.append(output_path)

                if progress_callback:
                    progress_callback(idx + 1, len(segments))

                priority_label = {1: "장면전환", 2: "중간동적", 3: "저동적"}[segment.priority]
                print(f"   ✓ segment_{idx+1:03d}.mp4 ({segment.duration:.1f}초, "
                      f"Motion: {segment.avg_motion:.2f}, Scene: {segment.avg_scene_change:.2f}, "
                      f"우선순위: {priority_label})")
            except subprocess.CalledProcessError as e:
                print(f"   ⚠️ segment_{idx+1:03d}.mp4 생성 실패: {e.stderr}")

        # 채택되지 않은 구간 저장 (실험 기능)
        if self.config.save_discarded:
            self._export_discarded_segments(video_path, segments, output_dir)

        # GPU 메모리 정리 (GPU 가속 사용 시)
        if self.gpu_available and self.device and self.device.type == 'cuda':
            try:
                import torch
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            except:
                pass

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
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
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
                'motion_low_threshold': self.config.motion_low_threshold,
                'motion_high_threshold': self.config.motion_high_threshold,
                'scene_change_threshold': self.config.scene_change_threshold,
                'scene_change_important': self.config.scene_change_important,
                'min_duration': self.config.min_duration,
                'max_duration': self.config.max_duration,
                'flow_scale': self.config.flow_scale,
                'frame_skip': self.config.frame_skip,
                'use_gpu': self.config.use_gpu,
                'priority_ratios': self.config.priority_ratios,
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
                    'avg_motion': seg.avg_motion,
                    'avg_scene_change': seg.avg_scene_change,
                    'priority': seg.priority
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
        print(f"   - 우선순위별 세그먼트:")
        print(f"     · 1순위 (장면전환): {self.stats['priority_1_segments']:,}개")
        print(f"     · 2순위 (중간동적): {self.stats['priority_2_segments']:,}개")
        print(f"     · 3순위 (저동적): {self.stats['priority_3_segments']:,}개")
        print(f"   - 제외 (짧음): {self.stats['discarded_short']:,}개")
        print(f"   - 제외 (저움직임): {self.stats['discarded_low_motion']:,}개")

        # Optical Flow 성능 통계
        gpu_count = self.stats['flow_gpu_count']
        cpu_count = self.stats['flow_cpu_count']
        gpu_time = self.stats['flow_gpu_time']
        cpu_time = self.stats['flow_cpu_time']

        if gpu_count > 0 or cpu_count > 0:
            print(f"\n⚡ Optical Flow 성능 통계:")
            if gpu_count > 0:
                avg_gpu_time = (gpu_time / gpu_count) * 1000  # ms
                print(f"   - GPU Flow: {gpu_count:,}회, 평균 {avg_gpu_time:.2f}ms/프레임, 총 {gpu_time:.2f}초")
            if cpu_count > 0:
                avg_cpu_time = (cpu_time / cpu_count) * 1000  # ms
                print(f"   - CPU Flow: {cpu_count:,}회, 평균 {avg_cpu_time:.2f}ms/프레임, 총 {cpu_time:.2f}초")
            if gpu_count > 0 and cpu_count > 0:
                speedup = (cpu_time / cpu_count) / (gpu_time / gpu_count)
                print(f"   - GPU 가속 배율: {speedup:.1f}x")


def main():
    parser = argparse.ArgumentParser(
        description="Optical Flow 기반 스마트 비디오 세그멘테이션"
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
        '--motion-low',
        type=float,
        default=2.0,
        help="저동적 구간 임계값 - 이보다 낮으면 제외 (기본: 2.0)"
    )
    parser.add_argument(
        '--motion-high',
        type=float,
        default=15.0,
        help="고동적 구간 임계값 - 이보다 높으면 과도한 움직임으로 제외 (기본: 15.0)"
    )
    parser.add_argument(
        '--scene-threshold',
        type=float,
        default=0.5,
        help="장면 전환 임계값 (히스토그램 차이, 기본: 0.5)"
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
        '--flow-scale',
        type=float,
        default=0.5,
        help="Optical Flow 계산 시 해상도 스케일 (0.5=2배 빠름, 1.0=원본, 기본: 0.5)"
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
        motion_low_threshold=args.motion_low,
        motion_high_threshold=args.motion_high,
        scene_change_threshold=args.scene_threshold,
        scene_change_important=args.scene_threshold,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        max_segments=args.max_segments,
        flow_scale=args.flow_scale,
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
