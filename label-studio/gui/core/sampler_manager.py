#!/usr/bin/env python3
"""
비디오 세그멘터 관리 모듈
video_segmenter.py를 GUI에서 사용하기 쉽게 래핑
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
    global VideoSegmenter, SegmentConfig
    if 'VideoSegmenter' not in globals():
        from tools.video_segmenter import VideoSegmenter, SegmentConfig


@dataclass
class SegmentationResult:
    """세그멘테이션 결과"""
    success: bool
    message: str
    output_path: Optional[Path] = None
    total_segments: int = 0
    total_duration: float = 0.0


class SamplerManager:
    """비디오 세그멘터 관리자"""

    def __init__(self):
        """세그멘터 관리자 초기화"""
        self.segmenter = None

    def segment_video(
        self,
        input_video: Path,
        output_dir: Path,
        scene_threshold: float = 0.3,
        static_threshold: float = 0.95,
        min_duration: float = 5.0,
        max_duration: float = 60.0,
        max_segments: Optional[int] = None,
        ssim_scale: float = 0.25,
        frame_skip: int = 1,
        save_discarded: bool = False,
        use_gpu: bool = False,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> SegmentationResult:
        """
        비디오 세그멘테이션 실행 (정적인 '잠수 구간'만 제외)

        Args:
            input_video: 입력 비디오 경로
            output_dir: 출력 디렉토리
            scene_threshold: 장면 전환 임계값 (기본: 0.3)
            static_threshold: 정적 구간 임계값 (기본: 0.95, 이보다 높으면 잠수 구간으로 제외)
            min_duration: 최소 클립 길이 (초)
            max_duration: 최대 클립 길이 (초)
            max_segments: 최대 클립 수
            ssim_scale: SSIM 계산 해상도 스케일 (기본: 0.25, 4-16배 빠름, 출력은 원본 유지)
            frame_skip: 프레임 스킵 (1=모든 프레임, 3=3프레임마다)
            save_discarded: 채택되지 않은 구간도 저장
            use_gpu: GPU 가속 사용 (기본: False, CUDA 필요)
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
                static_threshold=static_threshold,
                min_duration=min_duration,
                max_duration=max_duration,
                max_segments=max_segments,
                ssim_scale=ssim_scale,
                frame_skip=frame_skip,
                save_discarded=save_discarded,
                use_gpu=use_gpu
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
