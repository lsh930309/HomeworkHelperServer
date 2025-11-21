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

    # 동적 구간 감지 (적절한 배경 변화)
    dynamic_low_threshold: float = 0.4    # SSIM 최소값 (이보다 낮으면 너무 동적)
    dynamic_high_threshold: float = 0.8   # SSIM 최대값 (이보다 높으면 너무 정적)
    min_dynamic_frames: int = 30          # 최소 동적 프레임 수 (1초@30fps)

    # 세그먼트 제약
    min_duration: float = 5.0            # 최소 세그먼트 길이 (초)
    max_duration: float = 60.0           # 최대 세그먼트 길이 (초)
    max_segments: Optional[int] = None   # 최대 세그먼트 수

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
            'discarded_chaotic': 0
        }

    def calculate_ssim(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """두 이미지 간 SSIM 계산"""
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
        비디오에서 배경이 동적인 세그먼트 탐지 (UI는 고정, 배경만 변함)

        Args:
            video_path: 입력 비디오 경로
            progress_callback: 진행 상황 콜백 함수(current, total)

        Returns:
            VideoSegment 리스트
        """
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

        segments = []
        current_segment_start = 0
        dynamic_frame_count = 0
        ssim_buffer = []

        ret, prev_frame = cap.read()
        if not ret:
            raise RuntimeError("첫 프레임을 읽을 수 없습니다")

        frame_idx = 0

        while True:
            ret, current_frame = cap.read()
            if not ret:
                break

            frame_idx += 1

            if progress_callback and frame_idx % 100 == 0:
                progress_callback(frame_idx, total_frames)

            # SSIM 계산
            ssim_score = self.calculate_ssim(prev_frame, current_frame)
            ssim_buffer.append(ssim_score)

            # 장면 전환 감지
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
                        elif segment.avg_ssim > self.config.dynamic_high_threshold:
                            self.stats['discarded_static'] += 1
                        else:
                            self.stats['discarded_chaotic'] += 1

                # 새 세그먼트 시작
                current_segment_start = frame_idx
                dynamic_frame_count = 0
                ssim_buffer = []

            # 동적 구간 카운트 (SSIM이 적절한 범위 내)
            elif (self.config.dynamic_low_threshold <= ssim_score <=
                  self.config.dynamic_high_threshold):
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

        # 동적 범위 체크 (평균 SSIM이 적절한 범위 내)
        if not (self.config.dynamic_low_threshold <= segment.avg_ssim <=
                self.config.dynamic_high_threshold):
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
        세그먼트를 개별 비디오 파일로 저장

        Args:
            video_path: 원본 비디오 경로
            segments: 세그먼트 리스트
            output_dir: 출력 디렉토리
            progress_callback: 진행 상황 콜백

        Returns:
            저장된 비디오 파일 경로 리스트
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise RuntimeError(f"비디오를 열 수 없습니다: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        output_fps = self.config.output_fps or fps
        fourcc = cv2.VideoWriter_fourcc(*self.config.output_codec)

        saved_paths = []

        print(f"\n🎬 세그먼트 비디오 생성 중...")

        for idx, segment in enumerate(segments):
            output_path = output_dir / f"segment_{idx+1:03d}.mp4"

            # VideoWriter 생성
            writer = cv2.VideoWriter(
                str(output_path),
                fourcc,
                output_fps,
                (width, height)
            )

            # 시작 위치로 이동
            cap.set(cv2.CAP_PROP_POS_FRAMES, segment.start_frame)

            # 프레임 복사
            frame_count = segment.end_frame - segment.start_frame
            for i in range(frame_count):
                ret, frame = cap.read()
                if not ret:
                    break
                writer.write(frame)

            writer.release()
            saved_paths.append(output_path)

            if progress_callback:
                progress_callback(idx + 1, len(segments))

            print(f"   ✓ segment_{idx+1:03d}.mp4 ({segment.duration:.1f}초, "
                  f"SSIM: {segment.avg_ssim:.3f})")

        cap.release()

        print(f"\n✅ {len(saved_paths)}개 세그먼트 저장 완료!")
        return saved_paths

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
                'dynamic_low_threshold': self.config.dynamic_low_threshold,
                'dynamic_high_threshold': self.config.dynamic_high_threshold,
                'min_duration': self.config.min_duration,
                'max_duration': self.config.max_duration,
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
        print(f"   - 제외 (정적): {self.stats['discarded_static']:,}개")
        print(f"   - 제외 (혼란): {self.stats['discarded_chaotic']:,}개")


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
        '--dynamic-low',
        type=float,
        default=0.4,
        help="동적 범위 최소값 (기본: 0.4)"
    )
    parser.add_argument(
        '--dynamic-high',
        type=float,
        default=0.8,
        help="동적 범위 최대값 (기본: 0.8)"
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

    args = parser.parse_args()

    # 설정 생성
    config = SegmentConfig(
        scene_change_threshold=args.scene_threshold,
        dynamic_low_threshold=args.dynamic_low,
        dynamic_high_threshold=args.dynamic_high,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        max_segments=args.max_segments
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
