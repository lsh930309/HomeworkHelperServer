#!/usr/bin/env python3
"""
SSIM 샘플러 관리 모듈
video_sampler.py와 video_segmenter.py를 GUI에서 사용하기 쉽게 래핑
"""

import sys
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass

# tools 디렉토리를 sys.path에 추가
if getattr(sys, 'frozen', False):
    # PyInstaller 패키징 환경
    tools_dir = Path(sys.executable).parent / "_internal" / "tools"
else:
    # 개발 환경
    tools_dir = Path(__file__).parent.parent.parent.parent / "tools"

if str(tools_dir) not in sys.path:
    sys.path.insert(0, str(tools_dir))

# Lazy import: 함수 내부에서 import (순환 참조 및 경로 문제 방지)
def _import_tools():
    """tools 모듈을 lazy import"""
    global VideoSampler, SamplingConfig, VideoSegmenter, SegmentConfig
    if 'VideoSampler' not in globals():
        from tools.video_sampler import VideoSampler, SamplingConfig
        from tools.video_segmenter import VideoSegmenter, SegmentConfig


@dataclass
class SamplingResult:
    """샘플링 결과"""
    success: bool
    message: str
    output_path: Optional[Path] = None
    total_frames: int = 0
    sampled_frames: int = 0
    sampling_ratio: float = 0.0


@dataclass
class SegmentationResult:
    """세그멘테이션 결과"""
    success: bool
    message: str
    output_path: Optional[Path] = None
    total_segments: int = 0
    total_duration: float = 0.0


class SamplerManager:
    """SSIM 샘플러 관리자"""

    def __init__(self):
        """샘플러 관리자 초기화"""
        self.sampler: Optional[VideoSampler] = None
        self.segmenter: Optional[VideoSegmenter] = None

    def sample_video(
        self,
        input_video: Path,
        output_dir: Path,
        ssim_high: float = 0.98,
        ssim_low: float = 0.85,
        interval: float = 5.0,
        max_frames: Optional[int] = None,
        quality: int = 95,
        resize_width: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> SamplingResult:
        """
        비디오 샘플링 실행

        Args:
            input_video: 입력 비디오 경로
            output_dir: 출력 디렉토리
            ssim_high: SSIM 높은 임계값
            ssim_low: SSIM 낮은 임계값
            interval: 주기 샘플링 간격 (초)
            max_frames: 최대 샘플링 프레임 수
            quality: JPEG 품질 (1-100)
            resize_width: 리사이즈 너비 (None이면 원본)
            progress_callback: 진행 상황 콜백 (current, total)

        Returns:
            SamplingResult
        """
        # tools 모듈 import (lazy loading)
        _import_tools()

        try:
            # 입력 파일 확인
            if not input_video.exists():
                return SamplingResult(
                    success=False,
                    message=f"입력 비디오를 찾을 수 없습니다: {input_video}"
                )

            # 출력 디렉토리 생성
            output_dir.mkdir(parents=True, exist_ok=True)

            # 샘플링 설정
            config = SamplingConfig(
                ssim_high_threshold=ssim_high,
                ssim_low_threshold=ssim_low,
                interval_seconds=interval,
                output_quality=quality,
                resize_width=resize_width
            )

            # 샘플러 생성
            self.sampler = VideoSampler(config)

            # 샘플링 실행
            saved_paths = self.sampler.sample_video(
                input_video,
                output_dir,
                max_frames,
                progress_callback
            )

            # 메타데이터 저장
            self.sampler.save_metadata(output_dir, input_video)

            # 결과 반환
            stats = self.sampler.stats
            return SamplingResult(
                success=True,
                message=f"샘플링 완료: {len(saved_paths)}개 프레임 저장",
                output_path=output_dir,
                total_frames=stats['total_frames'],
                sampled_frames=stats['sampled_frames'],
                sampling_ratio=stats['sampled_frames'] / max(stats['total_frames'], 1) * 100
            )

        except Exception as e:
            return SamplingResult(
                success=False,
                message=f"샘플링 중 오류 발생: {e}"
            )

    def segment_video(
        self,
        input_video: Path,
        output_dir: Path,
        scene_threshold: float = 0.3,
        dynamic_low: float = 0.4,
        dynamic_high: float = 0.8,
        min_duration: float = 5.0,
        max_duration: float = 60.0,
        max_segments: Optional[int] = None,
        ssim_scale: float = 0.25,
        frame_skip: int = 1,
        save_discarded: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> SegmentationResult:
        """
        비디오 세그멘테이션 실행 (동적 배경 구간 선택)

        Args:
            input_video: 입력 비디오 경로
            output_dir: 출력 디렉토리
            scene_threshold: 장면 전환 임계값 (기본: 0.3)
            dynamic_low: 동적 범위 최소값 (기본: 0.4)
            dynamic_high: 동적 범위 최대값 (기본: 0.8)
            min_duration: 최소 클립 길이 (초)
            max_duration: 최대 클립 길이 (초)
            max_segments: 최대 클립 수
            ssim_scale: SSIM 계산 해상도 스케일 (기본: 0.25, 4-16배 빠름, 출력은 원본 유지)
            frame_skip: 프레임 스킵 (1=모든 프레임, 3=3프레임마다)
            save_discarded: 채택되지 않은 구간도 저장
            progress_callback: 진행 상황 콜백 (current, total)

        Returns:
            SegmentationResult
        """
        # tools 모듈 import (lazy loading)
        _import_tools()

        try:
            # 입력 파일 확인
            if not input_video.exists():
                return SegmentationResult(
                    success=False,
                    message=f"입력 비디오를 찾을 수 없습니다: {input_video}"
                )

            # 출력 디렉토리 생성
            output_dir.mkdir(parents=True, exist_ok=True)

            # 세그멘테이션 설정
            config = SegmentConfig(
                scene_change_threshold=scene_threshold,
                dynamic_low_threshold=dynamic_low,
                dynamic_high_threshold=dynamic_high,
                min_duration=min_duration,
                max_duration=max_duration,
                max_segments=max_segments,
                ssim_scale=ssim_scale,
                frame_skip=frame_skip,
                save_discarded=save_discarded
            )

            # 세그멘터 생성
            self.segmenter = VideoSegmenter(config)

            # 세그먼트 탐지
            segments = self.segmenter.detect_segments(
                input_video,
                progress_callback
            )

            if not segments:
                return SegmentationResult(
                    success=False,
                    message="유효한 세그먼트를 찾을 수 없습니다."
                )

            # 세그먼트 비디오 생성
            self.segmenter.export_segments(
                input_video,
                segments,
                output_dir,
                progress_callback
            )

            # 메타데이터 저장
            self.segmenter.save_metadata(output_dir, input_video, segments)

            # 총 길이 계산
            total_duration = sum(seg.duration for seg in segments)

            # 결과 반환
            return SegmentationResult(
                success=True,
                message=f"세그멘테이션 완료: {len(segments)}개 클립 생성",
                output_path=output_dir,
                total_segments=len(segments),
                total_duration=total_duration
            )

        except Exception as e:
            return SegmentationResult(
                success=False,
                message=f"세그멘테이션 중 오류 발생: {e}"
            )

    def cancel_current_operation(self):
        """현재 진행 중인 작업 취소"""
        # TODO: 취소 기능 구현 (sampler/segmenter에 cancel 플래그 추가 필요)
        pass

    @staticmethod
    def estimate_sampling_time(video_path: Path) -> Optional[float]:
        """
        샘플링 예상 시간 계산 (초)

        Args:
            video_path: 비디오 파일 경로

        Returns:
            예상 시간 (초) 또는 None
        """
        try:
            import cv2
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return None

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.release()

            # 대략적인 추정: 1000 프레임당 1초
            estimated_seconds = total_frames / 1000

            return estimated_seconds

        except Exception as e:
            print(f"예상 시간 계산 실패: {e}")
            return None

    @staticmethod
    def get_video_info(video_path: Path) -> Optional[dict]:
        """
        비디오 정보 반환

        Args:
            video_path: 비디오 파일 경로

        Returns:
            비디오 정보 딕셔너리 또는 None
        """
        try:
            import cv2
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                return None

            info = {
                'width': int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                'height': int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                'fps': cap.get(cv2.CAP_PROP_FPS),
                'total_frames': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                'duration': int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / cap.get(cv2.CAP_PROP_FPS)
            }
            cap.release()

            return info

        except Exception as e:
            print(f"비디오 정보 가져오기 실패: {e}")
            return None
