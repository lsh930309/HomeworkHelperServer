#!/usr/bin/env python3
"""
ResNet 기반 스마트 비디오 세그멘테이션
비디오를 의미적 유사도 기반으로 분할하여 정적 구간 제거 및 라벨링 효율 극대화
코사인 유사도를 사용한 프레임 간 비교로 더 정확한 장면 전환 감지

사용법:
    python tools/video_segmenter.py --input datasets/raw/gameplay.mp4 \
                                     --output datasets/clips/ \
                                     --mode auto \
                                     --use-gpu
"""

import argparse
import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass
import json
from datetime import datetime
from skimage.metrics import structural_similarity as ssim  # Legacy, 사용 안함
import subprocess
import shutil
import sys
import os
import bisect
import atexit
import signal
import gc
import time
import threading
import queue
from contextlib import contextmanager


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


class GPUResourceManager:
    """
    GPU 리소스 자동 관리 Context Manager
    작업 완료/취소/오류 시 자동으로 VRAM 정리
    """
    def __init__(self, device=None):
        self.device = device
        self.is_cuda = device and device.type == 'cuda'

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """무조건 VRAM 정리 (정상 종료/예외 모두)"""
        if self.is_cuda:
            try:
                import torch
                print("\n🧹 GPU 메모리 정리 중...")
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                gc.collect()

                memory_allocated = torch.cuda.memory_allocated(0) / 1024 / 1024
                memory_reserved = torch.cuda.memory_reserved(0) / 1024 / 1024
                print(f"   GPU 메모리 할당: {memory_allocated:.1f} MB")
                print(f"   GPU 메모리 예약: {memory_reserved:.1f} MB")
                print(f"   ✅ GPU 메모리 정리 완료")
            except Exception as e:
                print(f"   ⚠️ GPU 메모리 정리 실패 (무시됨): {e}")
        return False  # 예외를 다시 발생시킴


def extract_keyframes(video_path: Path) -> List[float]:
    """
    비디오의 모든 I-Frame(Keyframe) 타임스탬프 추출
    
    1. 고속 모드 (Packet Header): 컨테이너의 패킷 플래그만 확인 (매우 빠름)
    2. 정밀 모드 (Frame Decode): 실제 프레임 디코딩 (느림, 고속 모드 실패 시 Fallback)

    Args:
        video_path: 비디오 파일 경로

    Returns:
        Keyframe 타임스탬프 리스트 (초 단위, 정렬됨)
    """
    print("🔍 Keyframe 인덱싱 시작 (고속 모드)...")
    
    # 1. 고속 모드 시도 (Packet)
    try:
        cmd = [
            'ffprobe',
            '-select_streams', 'v:0',
            '-show_entries', 'packet=pts_time,flags',
            '-of', 'csv=print_section=0',
            str(video_path)
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            encoding='utf-8',
            errors='replace'
        )

        keyframes = []
        last_log_time = time.time()
        
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if not line:
                continue

            # pts_time, flags (e.g., "12.345,K__")
            parts = line.strip().split(',')
            if len(parts) >= 2:
                pts_time, flags = parts[0], parts[1]
                # 'K' 플래그가 있으면 Keyframe
                if 'K' in flags and pts_time != 'N/A':
                    try:
                        keyframes.append(float(pts_time))
                    except ValueError:
                        continue
            
            current_time = time.time()
            if current_time - last_log_time > 5.0:
                print(f"   키프레임 인덱싱 중 (고속)... ({len(keyframes)}개 발견)", flush=True)
                last_log_time = current_time

        process.wait(timeout=60) # 패킷 스캔은 매우 빠르므로 타임아웃 짧게

        if process.returncode == 0 and keyframes:
            keyframes.sort()
            print(f"✅ Keyframe {len(keyframes)}개 인덱싱 완료 (고속 모드)", flush=True)
            return keyframes
        
        print("⚠️ 고속 모드 인덱싱 실패 또는 키프레임 없음. 정밀 모드로 전환합니다.")

    except Exception as e:
        print(f"⚠️ 고속 모드 오류: {e}. 정밀 모드로 전환합니다.")
        if 'process' in locals() and process:
            try:
                process.kill()
            except:
                pass

    # 2. 정밀 모드 (Fallback)
    return _extract_keyframes_deep_scan(video_path)


def _extract_keyframes_deep_scan(video_path: Path) -> List[float]:
    """
    정밀 모드: ffprobe frame 디코딩을 통한 Keyframe 추출 (느림)
    """
    print("🔍 Keyframe 인덱싱 시작 (정밀 모드 - 시간이 걸릴 수 있습니다)...")
    try:
        cmd = [
            'ffprobe',
            '-select_streams', 'v:0',
            '-show_entries', 'frame=pts_time,pict_type',
            '-of', 'csv=print_section=0',
            str(video_path)
        ]

        # Popen으로 프로세스 실행 (스트리밍 출력)
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            encoding='utf-8',
            errors='replace'
        )

        keyframes = []
        last_log_time = time.time()
        
        # stdout 라인별 읽기
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if not line:
                continue

            parts = line.strip().split(',')
            if len(parts) >= 2:
                pts_time, pict_type = parts[0], parts[1]
                if pict_type == 'I' and pts_time != 'N/A':
                    try:
                        keyframes.append(float(pts_time))
                    except ValueError:
                        continue
            
            # 5초마다 진행 상황 로깅
            current_time = time.time()
            if current_time - last_log_time > 5.0:
                print(f"   키프레임 인덱싱 중 (정밀)... ({len(keyframes)}개 발견)", flush=True)
                last_log_time = current_time

        # 타임아웃 처리 (300초)
        try:
            process.wait(timeout=300)
        except subprocess.TimeoutExpired:
            process.kill()
            print("⚠️ Keyframe 추출 시간 초과 (5분), 부분 결과만 사용합니다.")
        
        if process.returncode != 0 and process.returncode is not None:
             # stderr 읽기
            stderr_output = process.stderr.read()
            print(f"⚠️ Keyframe 추출 경고 (ffprobe): {stderr_output[:200]}")

        keyframes.sort()
        print(f"✅ Keyframe {len(keyframes)}개 인덱싱 완료 (정밀 모드)", flush=True)
        return keyframes

    except Exception as e:
        print(f"⚠️ Keyframe 추출 실패: {e}, Keyframe 정렬 비활성화")
        return []


def snap_to_keyframe(time: float, keyframes: List[float], direction: str = 'before') -> float:
    """
    주어진 시간을 가장 가까운 Keyframe으로 정렬

    Args:
        time: 대상 시간 (초)
        keyframes: Keyframe 타임스탬프 리스트 (정렬됨)
        direction: 'before' (이전 keyframe) 또는 'after' (다음 keyframe)

    Returns:
        정렬된 시간 (초)
    """
    if not keyframes:
        return time

    idx = bisect.bisect_left(keyframes, time)

    if direction == 'before':
        # 정확히 일치하는 경우 해당 Keyframe 반환
        if idx < len(keyframes) and abs(keyframes[idx] - time) < 1e-5:
            return keyframes[idx]
            
        # 이전 Keyframe
        if idx == 0:
            return keyframes[0]
        return keyframes[idx - 1]
    else:
        # 다음 Keyframe
        if idx >= len(keyframes):
            return keyframes[-1]
        return keyframes[idx]


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


class FrameReader(threading.Thread):
    """
    별도 스레드에서 프레임을 미리 읽어오는 클래스 (I/O 병목 해결)
    Producer-Consumer 패턴 사용
    """
    def __init__(self, cap, queue_size=64):
        super().__init__()
        self.cap = cap
        self.queue = queue.Queue(maxsize=queue_size)
        self.stop_event = threading.Event()
        self.daemon = True  # 메인 스레드 종료 시 자동 종료

    def run(self):
        """프레임 읽기 루프 (Producer)"""
        while not self.stop_event.is_set():
            try:
                ret, frame = self.cap.read()
                if not ret:
                    # EOF 도달 시 None을 넣어 알림
                    self.queue.put((False, None))
                    break
                
                # 큐에 넣기 (꽉 차면 대기)
                self.queue.put((True, frame))
            except Exception as e:
                print(f"⚠️ FrameReader 오류: {e}")
                self.queue.put((False, None))
                break

    def read(self):
        """프레임 가져오기 (Consumer)"""
        try:
            # 큐에서 가져오기 (타임아웃 5초)
            return self.queue.get(timeout=5)
        except queue.Empty:
            return False, None

    def stop(self):
        """스레드 종료 요청"""
        self.stop_event.set()
        # 큐 비우기 (데드락 방지)
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break


@dataclass
class VideoSegment:
    """비디오 세그먼트 정보"""
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    duration: float
    avg_ssim: float  # 구간 내 평균 SSIM (안정성 지표)
    intervals: Optional[List[Tuple[float, float]]] = None  # Virtual Timeline: 여러 구간 [(start, end), ...]


@dataclass
class SegmentConfig:
    """세그멘테이션 설정"""
    # 모드 설정
    mode: str = "custom"                 # "custom" 고정

    # 정적 구간 감지 (ResNet 코사인 유사도 기준)
    static_threshold: float = 0.95       # 코사인 유사도가 이보다 높으면 너무 정적 (제외)
    min_static_duration: float = 1.0     # 최소 정적 구간 길이 (초)

    # 출력 세그먼트 설정
    target_segment_duration: float = 30.0  # 목표 세그먼트 길이 (초)

    # ResNet Feature 추출 설정
    feature_sample_rate: int = 1         # N프레임마다 feature 추출 (성능 최적화)
    enable_visualization: bool = True    # 유사도 그래프 출력 여부

    # 성능 최적화 (deprecated, 호환성 유지)
    ssim_scale: float = 1.0              # (사용 안 함, 호환성 유지)
    frame_skip: int = 1                  # (사용 안 함, feature_sample_rate로 대체됨)
    use_gpu: bool = False                # GPU 가속 사용 (CUDA 필수)
    initial_batch_size: int = 128        # 초기 배치 크기 (동적 조정됨)
    max_vram_usage: float = 0.85         # 최대 VRAM 사용률 (85%)

    # 실험 기능
    save_discarded: bool = False         # 채택되지 않은 구간도 별도 저장
    enable_keyframe_snap: bool = True    # Keyframe 정렬 활성화

    # 인코딩 설정
    re_encode: bool = False              # 재인코딩 여부 (True=재인코딩, False=스트림 복사)
    encode_quality: int = 0             # 인코딩 품질 (CRF, 0~51, 낮을수록 고화질)
    encode_preset: str = 'fast'          # 인코딩 프리셋 (ultrafast ~ veryslow)


class VideoSegmenter:
    """ResNet 기반 비디오 세그멘테이션 (코사인 유사도)"""

    def __init__(self, config: SegmentConfig = None):
        self.config = config or SegmentConfig()
        self.stats = {
            'total_frames': 0,
            'static_segments_removed': 0,     # 제거된 정적 구간 수
            'output_segments': 0,             # 최종 출력 세그먼트 수
            'similarity_gpu_count': 0,        # GPU로 계산한 유사도 횟수
            'similarity_cpu_count': 0,        # CPU로 계산한 유사도 횟수
            'similarity_gpu_time': 0.0,       # GPU 유사도 총 시간 (초)
            'similarity_cpu_time': 0.0,       # CPU 유사도 총 시간 (초)
            'batch_size_adjustments': 0,      # 배치 크기 조정 횟수
        }

        # GPU 사용 가능 여부 확인
        self.gpu_available = False
        self.device = None
        self.current_batch_size = self.config.initial_batch_size
        self.keyframes = []  # Keyframe 타임스탬프 캐시
        self.feature_extractor = None  # ResNet Feature Extractor
        self.similarity_scores_cache = []  # 유사도 점수 캐시 (시각화용)

        if self.config.use_gpu:
            self.gpu_available = self._check_gpu_available()

        # Feature Extractor 초기화
        if self.gpu_available:
            try:
                from tools.feature_extractor import FeatureExtractor
                self.feature_extractor = FeatureExtractor(device=self.device, use_fp16=True)
            except Exception as e:
                print(f"⚠️ Feature Extractor 초기화 실패: {e}")
                print("   CPU 모드로 전환합니다.")
                self.gpu_available = False

        # 초기 상태 출력
        self._print_initial_status()

        # atexit/signal handler 등록 (VRAM 정리)
        self._register_cleanup_handlers()

    def _print_initial_status(self):
        """초기 설정 및 상태 출력"""
        print("=" * 60)
        print(f"🎥 비디오 세그멘터 초기화 (ResNet 기반)")
        print(f"   - 모드: {self.config.mode.upper()}")
        print(f"   - GPU 가속: {'활성화' if self.gpu_available else '비활성화'}")
        if self.gpu_available:
            import torch
            print(f"     • 장치: {torch.cuda.get_device_name(0)}")
            print(f"     • VRAM 제한: {self.config.max_vram_usage * 100:.0f}%")

        print(f"   - 설정:")
        print(f"     • 정적 임계값: {self.config.static_threshold}")
        print(f"     • 최소 정적 길이: {self.config.min_static_duration}초")
        print(f"     • 목표 세그먼트: {self.config.target_segment_duration}초")
        print(f"     • Feature 샘플링: {self.config.feature_sample_rate}프레임마다")
        print(f"     • 시각화: {'활성화' if self.config.enable_visualization else '비활성화'}")
        print("=" * 60, flush=True)


    def _register_cleanup_handlers(self):
        """atexit 및 signal handler 등록"""
        def cleanup():
            if self.gpu_available and self.device and self.device.type == 'cuda':
                try:
                    import torch
                    torch.cuda.empty_cache()
                    gc.collect()
                except:
                    pass

        atexit.register(cleanup)

        # Windows에서는 SIGBREAK, Unix에서는 SIGINT/SIGTERM
        if sys.platform == 'win32':
            try:
                signal.signal(signal.SIGBREAK, lambda sig, frame: cleanup())
            except:
                pass
        else:
            signal.signal(signal.SIGINT, lambda sig, frame: cleanup())
            signal.signal(signal.SIGTERM, lambda sig, frame: cleanup())

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

    def calculate_similarity(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """
        두 프레임 간 코사인 유사도 계산 (ResNet 기반)

        1. 이미지 → ResNet feature 추출 (512차원)
        2. L2 정규화
        3. 코사인 유사도 = 내적

        Returns:
            유사도 (0~1, 높을수록 유사)
        """
        # GPU 가속 필수 (Feature Extractor 사용)
        if self.feature_extractor is not None:
            import time
            start_time = time.perf_counter()

            # Feature 추출 (배치 크기 2)
            features = self.feature_extractor.extract_frame_features([img1, img2])

            if len(features) >= 2:
                # 코사인 유사도 계산
                score = self.feature_extractor.calculate_cosine_similarity(features[0], features[1])
                elapsed = time.perf_counter() - start_time

                self.stats['similarity_gpu_count'] += 1
                self.stats['similarity_gpu_time'] += elapsed
                return score

        # GPU 사용 불가 시 오류 발생
        raise RuntimeError("GPU Feature Extractor를 사용할 수 없습니다. GPU 가속을 활성화해주세요.")

    def _adjust_batch_size(self, error: Exception = None):
        """
        VRAM 사용량에 따라 동적으로 배치 크기 조정

        Args:
            error: OOM 에러가 발생한 경우 전달
        """
        if not self.gpu_available:
            return

        try:
            import torch

            # OOM 발생 시 배치 크기 감소
            if error and isinstance(error, torch.cuda.OutOfMemoryError):
                self.current_batch_size = max(1, self.current_batch_size // 2)
                self.stats['batch_size_adjustments'] += 1
                torch.cuda.empty_cache()
                print(f"⚠️ GPU 메모리 부족, 배치 크기 감소: {self.current_batch_size * 2} → {self.current_batch_size}")
                return

            # 가용 VRAM 체크 및 배치 크기 조정
            free_mem, total_mem = torch.cuda.mem_get_info(0)
            free_ratio = free_mem / total_mem
            
            # 1. 메모리 부족 시 배치 크기 감소 (Proactive)
            # 남은 메모리가 25% 미만이면 배치 크기 감소
            if free_ratio < (1 - self.config.max_vram_usage):
                if self.current_batch_size > 1:
                    old_size = self.current_batch_size
                    self.current_batch_size = max(1, self.current_batch_size // 2)
                    self.stats['batch_size_adjustments'] += 1
                    torch.cuda.empty_cache()  # 중요: 캐시 비우기
                    print(f"⚠️ VRAM 여유 부족 ({free_ratio*100:.1f}%), 배치 크기 감소: {old_size} → {self.current_batch_size}")
                return

            # 2. 메모리 여유 시 배치 크기 증가
            # 남은 메모리가 60% 이상이고 (보수적 접근) 현재 배치가 최대가 아니면 증가
            if free_ratio > 0.6 and self.current_batch_size < 512:
                old_size = self.current_batch_size
                self.current_batch_size = min(512, self.current_batch_size * 2)
                if old_size != self.current_batch_size:
                    self.stats['batch_size_adjustments'] += 1
                    print(f"🚀 GPU 여유 메모리 확보 ({free_ratio*100:.1f}%), 배치 크기 증가: {old_size} → {self.current_batch_size}")

        except Exception as e:
            # VRAM 조정 실패는 무시
            pass

    def _calculate_similarity_batch(self, frame_pairs: list) -> list:
        """
        배치 단위 유사도 계산 (ResNet 기반, GPU 최적화)

        1. 모든 프레임을 배치로 묶기
        2. ResNet forward pass (배치 처리)
        3. L2 정규화
        4. 페어별 코사인 유사도 계산

        Args:
            frame_pairs: [(img1, img2), ...] 프레임 쌍 리스트

        Returns:
            유사도 점수 리스트
        """
        if not frame_pairs:
            return []

        # Feature Extractor 필수 (GPU)
        if self.feature_extractor is not None:
            similarities = self.feature_extractor.calculate_similarity_batch(frame_pairs)
            return similarities

        # GPU 사용 불가 시 오류 발생
        raise RuntimeError("GPU Feature Extractor를 사용할 수 없습니다. GPU 가속을 활성화해주세요.")

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
        비디오에서 유효 구간 탐지 (Virtual Timeline 방식)

        1단계: 정적 구간 스캔 및 마킹
        2단계: 유효 구간 병합 (짧은 정적 구간 무시)
        3단계: 누적 시간 기반 세그먼트 분할

        Args:
            video_path: 입력 비디오 경로
            progress_callback: 진행 상황 콜백 함수(current, total)

        Returns:
            VideoSegment 리스트 (Virtual Timeline 기반)
        """
        # Keyframe 인덱싱 (활성화 시)
        if self.config.enable_keyframe_snap:
            print("🔍 Keyframe 인덱싱 중...")
            self.keyframes = extract_keyframes(video_path)

        # GPU Resource Manager 사용
        with GPUResourceManager(self.device):
            # 1단계: 정적 구간 탐지
            static_intervals = self._scan_static_intervals(video_path, progress_callback)

            # static_intervals 저장 (시각화용)
            self.static_intervals_cache = static_intervals

            # 2단계: 유효 구간 계산
            valid_intervals = self._compute_valid_intervals(static_intervals, video_path)

            # 3단계: Virtual Timeline 기반 세그먼트 분할
            segments = self._split_by_virtual_timeline(valid_intervals, video_path)

        return segments

    def _scan_static_intervals(
        self,
        video_path: Path,
        progress_callback=None
    ) -> List[Tuple[float, float]]:
        """
        1단계: 정적 구간 스캔

        Returns:
            정적 구간 리스트 [(start_time, end_time), ...]
        """
        # 1단계: OpenCV로 열기 시도
        cap = cv2.VideoCapture(str(video_path))
        using_pyav = False

        if not cap.isOpened():
            print("⚠️ OpenCV로 비디오를 열 수 없어 PyAV로 전환합니다.")
            cap = PyAVVideoReader(video_path)
            if not cap.open():
                raise RuntimeError(f"비디오를 열 수 없습니다: {video_path}")
            using_pyav = True

        fps = cap.get(cv2.CAP_PROP_FPS) if not using_pyav else cap.fps
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not using_pyav else cap.total_frames
        self.stats['total_frames'] = total_frames

        print(f"📹 비디오 분석 중...")
        print(f"   - FPS: {fps:.2f}")
        print(f"   - 총 프레임: {total_frames:,}개")
        print(f"   - 길이: {total_frames / fps / 60:.1f}분")
        print(f"   - Feature 샘플링: {self.config.feature_sample_rate}프레임마다")
        print(f"   - 동적 배치 크기: {self.current_batch_size} (자동 조정)")

        # 2단계: 첫 프레임 읽기 검증
        ret, prev_frame = cap.read()
        if not ret and not using_pyav:
            print("⚠️ OpenCV로 첫 프레임 읽기 실패. PyAV로 전환합니다.")
            cap.release()
            cap = PyAVVideoReader(video_path)
            if not cap.open():
                raise RuntimeError("PyAV로도 비디오를 열 수 없습니다")
            using_pyav = True
            fps = cap.fps
            total_frames = cap.total_frames
            self.stats['total_frames'] = total_frames
            ret, prev_frame = cap.read()

        if not ret:
            cap.release()
            raise RuntimeError("첫 프레임을 읽을 수 없습니다")

        frame_idx = 0
        static_intervals = []
        static_start = None
        consecutive_static_frames = 0

        import time
        last_update_time = time.time()
        UPDATE_INTERVAL = 0.1

        # GPU 배치 처리
        use_batch = self.feature_extractor is not None
        frame_batch = []
        frame_indices = []

        # 유사도 점수 캐시 초기화
        self.similarity_scores_cache = []

        # FrameReader 시작 (I/O 병렬 처리)
        reader = FrameReader(cap, queue_size=64)
        reader.start()

        try:
            while True:
                # FrameReader에서 프레임 가져오기
                ret, current_frame = reader.read()
                if not ret:
                    break

                frame_idx += 1

                # 프레임 샘플링 (feature_sample_rate 사용)
                if frame_idx % self.config.feature_sample_rate != 0:
                    prev_frame = current_frame
                    continue

                # 진행률 업데이트
                current_time = time.time()
                if progress_callback and (current_time - last_update_time >= UPDATE_INTERVAL):
                    progress_callback(frame_idx, total_frames)
                    last_update_time = current_time

                if use_batch:
                    frame_batch.append((prev_frame.copy(), current_frame.copy()))
                    frame_indices.append(frame_idx)

                    if len(frame_batch) >= self.current_batch_size:
                        try:
                            similarity_scores = self._calculate_similarity_batch(frame_batch)

                            for batch_idx, similarity_score in enumerate(similarity_scores):
                                # 유사도 점수 캐시에 저장 (시각화용)
                                self.similarity_scores_cache.append((frame_indices[batch_idx], similarity_score))

                                if similarity_score >= self.config.static_threshold:
                                    if static_start is None:
                                        static_start = (frame_indices[batch_idx] - 1) / fps
                                    consecutive_static_frames += 1
                                else:
                                    if static_start is not None and consecutive_static_frames * self.config.feature_sample_rate / fps >= self.config.min_static_duration:
                                        static_end = frame_indices[batch_idx] / fps
                                        static_intervals.append((static_start, static_end))
                                        self.stats['static_segments_removed'] += 1
                                    static_start = None
                                    consecutive_static_frames = 0

                            # 배치 크기 동적 조정
                            self._adjust_batch_size()

                            frame_batch.clear()
                            frame_indices.clear()

                        except Exception as e:
                            try:
                                import torch
                                if isinstance(e, torch.cuda.OutOfMemoryError):
                                    self._adjust_batch_size(e)
                                    frame_batch.clear()
                                    frame_indices.clear()
                                    continue
                            except ImportError:
                                pass
                            raise

                    prev_frame = current_frame
                    continue

                # CPU 단일 처리
                similarity_score = self.calculate_similarity(prev_frame, current_frame)

                # 유사도 점수 캐시에 저장
                self.similarity_scores_cache.append((frame_idx, similarity_score))

                if similarity_score >= self.config.static_threshold:
                    if static_start is None:
                        static_start = (frame_idx - 1) / fps
                    consecutive_static_frames += 1
                else:
                    if static_start is not None and consecutive_static_frames * self.config.feature_sample_rate / fps >= self.config.min_static_duration:
                        static_end = frame_idx / fps
                        static_intervals.append((static_start, static_end))
                        self.stats['static_segments_removed'] += 1
                    static_start = None
                    consecutive_static_frames = 0

                prev_frame = current_frame

        finally:
            # FrameReader 정리
            reader.stop()
            reader.join(timeout=1.0)
            cap.release()

        # 마지막 정적 구간 처리
        if static_start is not None and consecutive_static_frames * self.config.feature_sample_rate / fps >= self.config.min_static_duration:
            static_end = frame_idx / fps
            static_intervals.append((static_start, static_end))
            self.stats['static_segments_removed'] += 1

        print(f"\n✅ 정적 구간 {len(static_intervals)}개 탐지 완료")
        print(f"   - 유사도 점수 {len(self.similarity_scores_cache)}개 수집됨")
        return static_intervals

    def _compute_valid_intervals(
        self,
        static_intervals: List[Tuple[float, float]],
        video_path: Path
    ) -> List[Tuple[float, float]]:
        """
        2단계: 유효 구간 계산 (정적 구간 제외)

        Returns:
            유효 구간 리스트 [(start_time, end_time), ...]
        """
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        total_duration = total_frames / fps
        cap.release()

        if not static_intervals:
            return [(0.0, total_duration)]

        valid_intervals = []
        prev_end = 0.0

        for start, end in sorted(static_intervals):
            if start > prev_end + 0.1:  # 0.1초 이상 차이
                valid_intervals.append((prev_end, start))
            prev_end = end

        # 마지막 구간
        if prev_end < total_duration - 0.1:
            valid_intervals.append((prev_end, total_duration))

        total_valid_duration = sum(end - start for start, end in valid_intervals)
        print(f"✅ 유효 구간 {len(valid_intervals)}개 (총 {total_valid_duration / 60:.1f}분)")

        return valid_intervals

    def _split_by_virtual_timeline(
        self,
        valid_intervals: List[Tuple[float, float]],
        video_path: Path
    ) -> List[VideoSegment]:
        """
        3단계: Virtual Timeline 기반 세그먼트 분할 (개선된 로직)

        1. 모든 유효 구간에 Keyframe 스냅 적용
        2. 중복/겹침 제거 및 병합 → clean_intervals
        3. clean_intervals를 target_duration에 맞게 분할
        4. 최종 세그먼트 생성
        """
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()

        # ===== 1단계: Keyframe 스냅 적용 =====
        snapped_intervals = []
        for start, end in valid_intervals:
            if self.config.enable_keyframe_snap and self.keyframes:
                start = snap_to_keyframe(start, self.keyframes, 'before')
                end = snap_to_keyframe(end, self.keyframes, 'after')
            
            if end > start:
                snapped_intervals.append((start, end))

        if not snapped_intervals:
            return []

        # ===== 2단계: 중복 제거 및 병합 =====
        clean_intervals = self._merge_overlapping_intervals(snapped_intervals)
        
        total_clean_duration = sum(e - s for s, e in clean_intervals)
        print(f"🔧 Keyframe 스냅 후 구간 병합: {len(snapped_intervals)}개 → {len(clean_intervals)}개 (총 {total_clean_duration / 60:.1f}분)")

        # ===== 3단계: target_duration에 맞게 분할 =====
        segments = []
        accumulated_time = 0.0
        segment_intervals = []
        target = self.config.target_segment_duration

        for start, end in clean_intervals:
            current_pos = start
            
            while current_pos < end:
                remaining_for_segment = target - accumulated_time
                remaining_in_interval = end - current_pos
                
                if remaining_in_interval <= remaining_for_segment:
                    # 현재 interval을 전부 사용
                    segment_intervals.append((current_pos, end))
                    accumulated_time += remaining_in_interval
                    current_pos = end
                else:
                    # 현재 interval을 잘라서 세그먼트 완성
                    cut_point = current_pos + remaining_for_segment
                    
                    # Keyframe 스냅 (커팅 지점)
                    if self.config.enable_keyframe_snap and self.keyframes:
                        cut_point = snap_to_keyframe(cut_point, self.keyframes, 'before')
                        # 너무 짧으면 다음 keyframe으로
                        if cut_point <= current_pos + 1.0:
                            cut_point = snap_to_keyframe(current_pos + remaining_for_segment, self.keyframes, 'after')
                        # end를 넘지 않도록
                        cut_point = min(cut_point, end)
                    
                    actual_duration = cut_point - current_pos
                    
                    if actual_duration > 0:
                        segment_intervals.append((current_pos, cut_point))
                        accumulated_time += actual_duration
                    
                    # 세그먼트 생성
                    if segment_intervals:
                        seg_start = segment_intervals[0][0]
                        seg_end = segment_intervals[-1][1]
                        seg_duration = sum(e - s for s, e in segment_intervals)
                        
                        segments.append(VideoSegment(
                            start_frame=int(seg_start * fps),
                            end_frame=int(seg_end * fps),
                            start_time=seg_start,
                            end_time=seg_end,
                            duration=seg_duration,
                            avg_ssim=0.0,
                            intervals=list(segment_intervals)
                        ))
                    
                    # 다음 세그먼트 준비
                    current_pos = cut_point
                    accumulated_time = 0.0
                    segment_intervals = []
                
                # 무한 루프 방지
                if current_pos >= end:
                    break

        # 마지막 세그먼트
        if segment_intervals:
            seg_start = segment_intervals[0][0]
            seg_end = segment_intervals[-1][1]
            seg_duration = sum(e - s for s, e in segment_intervals)
            
            segments.append(VideoSegment(
                start_frame=int(seg_start * fps),
                end_frame=int(seg_end * fps),
                start_time=seg_start,
                end_time=seg_end,
                duration=seg_duration,
                avg_ssim=0.0,
                intervals=list(segment_intervals)
            ))

        self.stats['output_segments'] = len(segments)
        if segments:
            avg_duration = sum(s.duration for s in segments) / len(segments)
            print(f"✅ 최종 세그먼트 {len(segments)}개 생성 (평균 {avg_duration:.1f}초)")
        else:
            print("⚠️ 유효한 세그먼트가 없습니다.")

        return segments

    def _merge_overlapping_intervals(
        self,
        intervals: List[Tuple[float, float]]
    ) -> List[Tuple[float, float]]:
        """
        겹치거나 인접한 구간 병합
        """
        if not intervals:
            return []
        
        # 중복 제거 (소수점 3자리 반올림)
        seen = set()
        unique = []
        for s, e in intervals:
            key = (round(s, 3), round(e, 3))
            if key not in seen:
                seen.add(key)
                unique.append((s, e))
        
        # 정렬
        unique.sort(key=lambda x: x[0])
        
        # 병합
        merged = []
        for start, end in unique:
            if not merged:
                merged.append([start, end])
            else:
                last_start, last_end = merged[-1]
                # 겹치거나 인접 (0.1초 이내)
                if start <= last_end + 0.1:
                    merged[-1][1] = max(last_end, end)
                else:
                    merged.append([start, end])
        
        return [(s, e) for s, e in merged]

    def _deduplicate_segment_intervals(
        self,
        segments: List[VideoSegment],
        fps: float
    ) -> List[VideoSegment]:
        """
        세그먼트의 intervals 중복 제거 및 병합
        
        Keyframe 스냅으로 인해 같은 구간이 여러 번 포함될 수 있으므로:
        1. 각 세그먼트 내 중복 interval 제거
        2. 겹치거나 인접한 interval 병합
        3. 빈 세그먼트 제거
        4. duration 재계산
        """
        cleaned_segments = []
        
        for seg in segments:
            if not seg.intervals:
                continue
            
            # 1. 중복 제거 (순서 유지)
            seen = set()
            unique_intervals = []
            for interval in seg.intervals:
                # 튜플을 소수점 3자리로 반올림하여 비교 (부동소수점 오차 방지)
                key = (round(interval[0], 3), round(interval[1], 3))
                if key not in seen:
                    seen.add(key)
                    unique_intervals.append(interval)
            
            # 2. 정렬
            unique_intervals.sort(key=lambda x: x[0])
            
            # 3. 겹치거나 인접한 구간 병합
            merged_intervals = []
            for start, end in unique_intervals:
                if not merged_intervals:
                    merged_intervals.append([start, end])
                else:
                    last_start, last_end = merged_intervals[-1]
                    # 겹치거나 인접한 경우 (0.1초 이내)
                    if start <= last_end + 0.1:
                        merged_intervals[-1][1] = max(last_end, end)
                    else:
                        merged_intervals.append([start, end])
            
            # 튜플로 변환
            merged_intervals = [(s, e) for s, e in merged_intervals]
            
            # 4. 빈 구간 제거 및 duration 재계산
            valid_intervals = [(s, e) for s, e in merged_intervals if e > s]
            
            if not valid_intervals:
                continue
            
            # duration 재계산
            total_duration = sum(e - s for s, e in valid_intervals)
            
            # 새 세그먼트 생성
            seg_start = valid_intervals[0][0]
            seg_end = valid_intervals[-1][1]
            
            cleaned_segments.append(VideoSegment(
                start_frame=int(seg_start * fps),
                end_frame=int(seg_end * fps),
                start_time=seg_start,
                end_time=seg_end,
                duration=total_duration,
                avg_ssim=seg.avg_ssim,
                intervals=valid_intervals
            ))
        
        # 중복 제거 결과 로깅
        original_count = len(segments)
        cleaned_count = len(cleaned_segments)
        if original_count != cleaned_count:
            print(f"🔧 중복 제거: {original_count}개 → {cleaned_count}개 세그먼트")
        
        return cleaned_segments

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

    def _visualize_similarity_scores(
        self,
        output_dir: Path,
        fps: float,
        static_intervals: List[Tuple[float, float]],
        segments: List[VideoSegment]
    ):
        """
        유사도 점수 시각화 (./result_seg/similarity_graph.png)

        그래프 구성:
        - X축: 시간(초)
        - Y축: 유사도 점수 (0~1)
        - 빨간 영역: 정적 구간 (제거될 부분)
        - 녹색 영역: 유효 구간 (사용될 부분)
        - 파란 선: 세그먼트 경계 (30초 단위)
        """
        if not self.similarity_scores_cache:
            print("⚠️ 유사도 점수가 없어 시각화를 건너뜁니다.")
            return

        try:
            import matplotlib
            matplotlib.use('Agg')  # GUI 없는 환경 지원
            import matplotlib.pyplot as plt

            # 데이터 준비
            frame_numbers = [frame_idx for frame_idx, _ in self.similarity_scores_cache]
            scores = [score for _, score in self.similarity_scores_cache]
            times = [frame_idx / fps for frame_idx in frame_numbers]

            # 그래프 생성
            fig, ax = plt.subplots(figsize=(16, 6))

            # 유사도 점수 플롯
            ax.plot(times, scores, 'b-', linewidth=0.5, label='Cosine Similarity', alpha=0.7)

            # 정적 구간 표시 (빨간 배경)
            for start_time, end_time in static_intervals:
                ax.axvspan(start_time, end_time, color='red', alpha=0.2, label='Static Interval' if static_intervals.index((start_time, end_time)) == 0 else '')

            # 세그먼트 경계 표시 (파란 세로선)
            for idx, segment in enumerate(segments):
                ax.axvline(x=segment.start_time, color='blue', linestyle='--', linewidth=1.5, alpha=0.7, label='Segment Boundary' if idx == 0 else '')

            # 임계값 선 표시
            ax.axhline(y=self.config.static_threshold, color='orange', linestyle=':', linewidth=2, label=f'Static Threshold ({self.config.static_threshold})')

            # 레이블 및 제목
            ax.set_xlabel('Time (seconds)', fontsize=12)
            ax.set_ylabel('Cosine Similarity', fontsize=12)
            ax.set_title('Video Similarity Analysis (ResNet-based)', fontsize=14, fontweight='bold')
            ax.set_ylim(0, 1.05)
            ax.grid(True, alpha=0.3)
            ax.legend(loc='upper right', fontsize=10)

            # 저장
            output_path = output_dir / 'similarity_graph.png'
            plt.tight_layout()
            plt.savefig(output_path, dpi=150)
            plt.close()

            print(f"📊 유사도 그래프 저장: {output_path}")

        except ImportError:
            print("⚠️ matplotlib가 설치되지 않아 시각화를 건너뜁니다.")
        except Exception as e:
            print(f"⚠️ 시각화 생성 실패: {e}")

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
        세그먼트를 개별 비디오 파일로 저장 (FFmpeg concat demuxer 사용)

        Virtual Timeline의 여러 구간을 이어붙여 최종 세그먼트 생성

        Args:
            video_path: 원본 비디오 경로
            segments: 세그먼트 리스트
            output_dir: 출력 디렉토리
            progress_callback: 진행 상황 콜백

        Returns:
            저장된 비디오 파일 경로 리스트
        """
        # 시각화 생성 (활성화된 경우)
        if self.config.enable_visualization:
            # FPS 가져오기
            cap = cv2.VideoCapture(str(video_path))
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()

            # static_intervals가 캐시되어 있는 경우에만 시각화
            static_intervals = getattr(self, 'static_intervals_cache', [])

            self._visualize_similarity_scores(
                output_dir=output_dir,
                fps=fps,
                static_intervals=static_intervals,
                segments=segments
            )

        # ffmpeg 확인 및 자동 설치
        if not check_and_install_ffmpeg():
            raise RuntimeError(
                "ffmpeg를 사용할 수 없습니다. "
                "터미널을 재시작하거나 수동으로 설치해주세요."
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        saved_paths = []

        print(f"\n🎬 세그먼트 비디오 생성 중 (FFmpeg {'재인코딩' if self.config.re_encode else 'concat demuxer'})...")

        for idx, segment in enumerate(segments):
            output_path = output_dir / f"segment_{idx+1:03d}.mp4"

            # 재인코딩 모드
            if self.config.re_encode:
                # 필터 복잡도 생성 (여러 구간 병합 시)
                filter_complex = ""
                inputs = []
                
                if segment.intervals:
                    # 여러 구간이 있는 경우
                    for i, (start, end) in enumerate(segment.intervals):
                        inputs.extend(['-ss', str(start), '-to', str(end), '-i', str(video_path)])
                        filter_complex += f"[{i}:v:0][{i}:a:0]"
                    
                    filter_complex += f"concat=n={len(segment.intervals)}:v=1:a=1[outv][outa]"
                    
                    cmd = [
                        'ffmpeg',
                        *inputs,
                        '-filter_complex', filter_complex,
                        '-map', '[outv]', '-map', '[outa]',
                        '-c:v', 'libx264',
                        '-crf', str(self.config.encode_quality),
                        '-preset', self.config.encode_preset,
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-y',
                        str(output_path)
                    ]
                else:
                    # 단일 구간 (이론상 intervals가 없는 경우는 없어야 하지만 방어 코드)
                    cmd = [
                        'ffmpeg',
                        '-ss', str(segment.start_time),
                        '-to', str(segment.end_time),
                        '-i', str(video_path),
                        '-c:v', 'libx264',
                        '-crf', str(self.config.encode_quality),
                        '-preset', self.config.encode_preset,
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-y',
                        str(output_path)
                    ]

                try:
                    subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    saved_paths.append(output_path)

                    if progress_callback:
                        progress_callback(idx + 1, len(segments))

                    print(f"   ✓ segment_{idx+1:03d}.mp4 ({segment.duration:.1f}초, 재인코딩 완료)")

                except subprocess.CalledProcessError as e:
                    print(f"   ⚠️ segment_{idx+1:03d}.mp4 생성 실패: {e.stderr}")

            # 스트림 복사 모드 (기존 방식)
            else:
                # 여러 구간을 concat해야 하는 경우
                if segment.intervals and len(segment.intervals) > 1:
                    # concat demuxer용 임시 파일 리스트 생성
                    concat_list_path = output_dir / f"_concat_{idx+1:03d}.txt"

                    with open(concat_list_path, 'w', encoding='utf-8') as f:
                        for interval_start, interval_end in segment.intervals:
                            # 각 구간마다 file, inpoint, outpoint 지정
                            # Windows 경로 이스케이프 처리 (.as_posix())
                            f.write(f"file '{video_path.absolute().as_posix()}'\n")
                            f.write(f"inpoint {interval_start}\n")
                            f.write(f"outpoint {interval_end}\n")

                    # FFmpeg concat demuxer 실행
                    cmd = [
                        'ffmpeg',
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', str(concat_list_path),
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
                            encoding='utf-8',
                            errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                        saved_paths.append(output_path)

                        if progress_callback:
                            progress_callback(idx + 1, len(segments))

                        print(f"   ✓ segment_{idx+1:03d}.mp4 ({segment.duration:.1f}초, {len(segment.intervals)}개 구간 병합)")

                        # 임시 파일 삭제
                        concat_list_path.unlink()

                    except subprocess.CalledProcessError as e:
                        print(f"   ⚠️ segment_{idx+1:03d}.mp4 생성 실패: {e.stderr}")
                        if concat_list_path.exists():
                            concat_list_path.unlink()

                else:
                    # 단일 구간인 경우 기존 방식 사용
                    cmd = [
                        'ffmpeg',
                        '-i', str(video_path),
                        '-ss', str(segment.start_time),
                        '-to', str(segment.end_time),
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
                            encoding='utf-8',
                            errors='replace',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                        saved_paths.append(output_path)

                        if progress_callback:
                            progress_callback(idx + 1, len(segments))

                        print(f"   ✓ segment_{idx+1:03d}.mp4 ({segment.duration:.1f}초)")

                    except subprocess.CalledProcessError as e:
                        print(f"   ⚠️ segment_{idx+1:03d}.mp4 생성 실패: {e.stderr}")

        print(f"\n✅ {len(saved_paths)}개 세그먼트 저장 완료!")
        
        # 버려진 구간 저장 (활성화된 경우)
        if self.config.save_discarded:
            self._export_discarded_segments(video_path, segments, output_dir)
        
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
                    encoding='utf-8',
                    errors='replace',
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
                'mode': self.config.mode,
                'static_threshold': self.config.static_threshold,
                'min_static_duration': self.config.min_static_duration,
                'target_segment_duration': self.config.target_segment_duration,
                'ssim_scale': self.config.ssim_scale,
                'frame_skip': self.config.frame_skip,
                'use_gpu': self.config.use_gpu,
                'enable_keyframe_snap': self.config.enable_keyframe_snap,
                're_encode': self.config.re_encode,
                'encode_quality': self.config.encode_quality,
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
                    'avg_ssim': seg.avg_ssim,
                    'num_intervals': len(seg.intervals) if seg.intervals else 1
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
        print(f"   - 제거된 정적 구간: {self.stats['static_segments_removed']:,}개")
        print(f"   - 최종 출력 세그먼트: {self.stats['output_segments']:,}개")

        # 유사도 성능 통계
        gpu_count = self.stats['similarity_gpu_count']
        cpu_count = self.stats['similarity_cpu_count']
        gpu_time = self.stats['similarity_gpu_time']
        cpu_time = self.stats['similarity_cpu_time']

        if gpu_count > 0 or cpu_count > 0:
            print(f"\n⚡ 유사도 계산 성능 통계:")
            if gpu_count > 0:
                avg_gpu_time = (gpu_time / gpu_count) * 1000  # ms
                print(f"   - GPU (ResNet): {gpu_count:,}회, 평균 {avg_gpu_time:.2f}ms/프레임, 총 {gpu_time:.2f}초")
            if cpu_count > 0:
                avg_cpu_time = (cpu_time / cpu_count) * 1000  # ms
                print(f"   - CPU (SSIM Fallback): {cpu_count:,}회, 평균 {avg_cpu_time:.2f}ms/프레임, 총 {cpu_time:.2f}초")
            if gpu_count > 0 and cpu_count > 0:
                speedup = (cpu_time / cpu_count) / (gpu_time / gpu_count)
                print(f"   - GPU 가속 배율: {speedup:.1f}x")

        # 배치 크기 조정 통계
        if self.stats['batch_size_adjustments'] > 0:
            print(f"\n🔧 동적 배치 조정:")
            print(f"   - 조정 횟수: {self.stats['batch_size_adjustments']:,}회")
            print(f"   - 최종 배치 크기: {self.current_batch_size}")


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
        '--mode',
        type=str,
        choices=['auto', 'custom'],
        default='auto',
        help="세그멘테이션 모드 (auto=자동 설정, custom=사용자 지정, 기본: auto)"
    )
    parser.add_argument(
        '--static-threshold',
        type=float,
        default=0.95,
        help="정적 구간 임계값 - 이보다 높으면 잠수 구간으로 제외 (기본: 0.95)"
    )
    parser.add_argument(
        '--min-static-duration',
        type=float,
        default=2.0,
        help="최소 정적 구간 길이 초 - 이보다 짧은 정적 구간은 무시 (기본: 2.0)"
    )
    parser.add_argument(
        '--target-duration',
        type=float,
        default=600.0,
        help="목표 세그먼트 길이 초 (기본: 600.0, 10분)"
    )
    parser.add_argument(
        '--ssim-scale',
        type=float,
        default=1.0,
        help="SSIM 계산 시 해상도 스케일 (0.25=4배 빠름, 1.0=원본, 기본: 1.0)"
    )
    parser.add_argument(
        '--frame-skip',
        type=int,
        default=1,
        help="프레임 스킵 (1=모든 프레임, 2=2프레임마다, 기본: 1)"
    )
    parser.add_argument(
        '--use-gpu',
        action='store_true',
        help="GPU 가속 사용 (CUDA 사용 가능 시)"
    )
    parser.add_argument(
        '--disable-keyframe-snap',
        action='store_true',
        help="Keyframe 정렬 비활성화 (기본: 활성화)"
    )
    parser.add_argument(
        '--re-encode',
        action='store_true',
        help="출력 시 재인코딩 수행 (버벅임 방지, 속도 느림)"
    )
    parser.add_argument(
        '--quality',
        type=int,
        default=23,
        help="인코딩 품질 (CRF, 0~51, 기본: 23, 낮을수록 고화질)"
    )
    parser.add_argument(
        '--preset',
        type=str,
        default='fast',
        help="인코딩 프리셋 (ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow)"
    )

    args = parser.parse_args()

    # 설정 생성
    config = SegmentConfig(
        mode=args.mode,
        static_threshold=args.static_threshold,
        min_static_duration=args.min_static_duration,
        target_segment_duration=args.target_duration,
        ssim_scale=args.ssim_scale,
        frame_skip=args.frame_skip,
        use_gpu=args.use_gpu,
        enable_keyframe_snap=not args.disable_keyframe_snap,
        re_encode=args.re_encode,
        encode_quality=args.quality,
        encode_preset=args.preset
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
