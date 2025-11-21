#!/usr/bin/env python3
"""
SSIM 기반 스마트 비디오 샘플링
비디오에서 유의미한 프레임만 추출하여 YOLO 라벨링 데이터셋 생성

사용법:
    python tools/video_sampler.py --input datasets/raw/session_01.mp4 \
                                   --output datasets/processed/ \
                                   --max-frames 500
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
import tempfile

# video_segmenter에서 FFmpeg 관련 함수 import
import sys
sys.path.insert(0, str(Path(__file__).parent))
try:
    from video_segmenter import check_and_install_ffmpeg, reencode_video_with_ffmpeg
except ImportError:
    # 함수들이 없으면 더미 함수 제공
    def check_and_install_ffmpeg():
        return False
    def reencode_video_with_ffmpeg(input_path, output_path):
        return False


@dataclass
class SamplingConfig:
    """샘플링 설정"""
    # SSIM 임계값
    ssim_high_threshold: float = 0.98  # 이보다 높으면 스킵 (거의 동일)
    ssim_low_threshold: float = 0.85   # 이보다 낮으면 저장 (유의미한 변화)

    # 샘플링 간격
    interval_seconds: float = 5.0      # 중간 SSIM일 때 샘플링 간격 (초)
    min_interval_frames: int = 30      # 최소 프레임 간격 (1초@30fps)

    # 출력 설정
    output_format: str = "jpg"         # jpg, png
    output_quality: int = 95           # JPEG 품질 (1-100)
    resize_width: Optional[int] = None # 리사이즈 너비 (None이면 원본)
    resize_height: Optional[int] = None

    # 장면 전환 감지
    scene_change_threshold: float = 0.5  # SSIM이 이보다 낮으면 장면 전환으로 간주


class VideoSampler:
    """SSIM 기반 스마트 비디오 샘플링"""

    def __init__(self, config: SamplingConfig = None):
        self.config = config or SamplingConfig()
        self.stats = {
            'total_frames': 0,
            'sampled_frames': 0,
            'skipped_idle': 0,      # 잠수 구간
            'scene_changes': 0,     # 장면 전환
            'interval_samples': 0   # 주기 샘플링
        }

    def calculate_ssim(self, img1: np.ndarray, img2: np.ndarray) -> float:
        """
        두 이미지 간 SSIM 계산

        Args:
            img1: 첫 번째 이미지 (BGR)
            img2: 두 번째 이미지 (BGR)

        Returns:
            SSIM 값 (0.0 ~ 1.0)
        """
        # 그레이스케일 변환
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)

        # SSIM 계산
        score, _ = ssim(gray1, gray2, full=True)
        return score

    def resize_frame(self, frame: np.ndarray) -> np.ndarray:
        """프레임 리사이즈 (설정된 경우)"""
        if self.config.resize_width is None and self.config.resize_height is None:
            return frame

        h, w = frame.shape[:2]

        if self.config.resize_width and self.config.resize_height:
            new_w, new_h = self.config.resize_width, self.config.resize_height
        elif self.config.resize_width:
            new_w = self.config.resize_width
            new_h = int(h * (new_w / w))
        else:
            new_h = self.config.resize_height
            new_w = int(w * (new_h / h))

        return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def should_sample(
        self,
        current_frame_idx: int,
        last_sampled_frame_idx: int,
        ssim_score: float,
        fps: float
    ) -> Tuple[bool, str]:
        """
        프레임을 샘플링해야 하는지 판단

        Returns:
            (샘플링 여부, 이유)
        """
        # 최소 간격 체크
        if current_frame_idx - last_sampled_frame_idx < self.config.min_interval_frames:
            return False, "min_interval"

        # 장면 전환 감지
        if ssim_score < self.config.scene_change_threshold:
            self.stats['scene_changes'] += 1
            return True, "scene_change"

        # 유의미한 변화 감지
        if ssim_score < self.config.ssim_low_threshold:
            return True, "significant_change"

        # 잠수 구간 (거의 동일)
        if ssim_score > self.config.ssim_high_threshold:
            self.stats['skipped_idle'] += 1
            return False, "idle"

        # 중간 SSIM: 주기적 샘플링
        interval_frames = int(self.config.interval_seconds * fps)
        if current_frame_idx - last_sampled_frame_idx >= interval_frames:
            self.stats['interval_samples'] += 1
            return True, "interval"

        return False, "no_condition"

    def sample_video(
        self,
        input_video_path: Path,
        output_dir: Path,
        max_frames: Optional[int] = None,
        progress_callback=None
    ) -> List[Path]:
        """
        비디오 샘플링 실행

        Args:
            input_video_path: 입력 비디오 경로
            output_dir: 출력 디렉토리
            max_frames: 최대 프레임 수 (None이면 무제한)
            progress_callback: 진행 상황 콜백 함수(current, total)

        Returns:
            저장된 이미지 경로 리스트
        """
        if not input_video_path.exists():
            raise FileNotFoundError(f"비디오 파일을 찾을 수 없습니다: {input_video_path}")

        output_dir.mkdir(parents=True, exist_ok=True)

        # 재인코딩된 임시 파일 추적용
        temp_video_path = None
        original_video_path = input_video_path

        # 비디오 열기
        cap = cv2.VideoCapture(str(input_video_path))
        if not cap.isOpened():
            raise RuntimeError(f"비디오를 열 수 없습니다: {input_video_path}")

        # 비디오 정보
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        print(f"📹 비디오 정보:")
        print(f"   - 해상도: {width}x{height}")
        print(f"   - FPS: {fps:.2f}")
        print(f"   - 총 프레임: {total_frames:,}개")
        print(f"   - 길이: {total_frames / fps / 60:.1f}분")

        self.stats['total_frames'] = total_frames

        # 첫 프레임 읽기 시도
        ret, prev_frame = cap.read()
        if not ret:
            # OpenCV로 첫 프레임 읽기 실패 -> FFmpeg 재인코딩 시도
            print("⚠️ OpenCV로 첫 프레임을 읽을 수 없습니다.")
            print("   비디오 코덱이 OpenCV와 호환되지 않을 수 있습니다.")
            cap.release()

            # 임시 파일 경로 생성
            temp_dir = Path(tempfile.gettempdir())
            temp_video_path = temp_dir / f"reencoded_{input_video_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"

            print(f"🔄 FFmpeg로 재인코딩을 시도합니다...")
            if not reencode_video_with_ffmpeg(input_video_path, temp_video_path):
                raise RuntimeError(
                    "첫 프레임을 읽을 수 없습니다.\n"
                    "비디오 파일이 손상되었거나 지원되지 않는 코덱을 사용합니다.\n"
                    f"문제가 계속되면 다음 도구로 수동 변환을 시도하세요:\n"
                    f"  ffmpeg -i \"{input_video_path}\" -c:v libx264 -c:a aac output.mp4"
                )

            # 재인코딩된 파일로 다시 시도
            print(f"✅ 재인코딩 완료. 다시 처리를 시도합니다...")
            input_video_path = temp_video_path
            cap = cv2.VideoCapture(str(input_video_path))

            if not cap.isOpened():
                if temp_video_path and temp_video_path.exists():
                    temp_video_path.unlink()
                raise RuntimeError(f"재인코딩된 비디오도 열 수 없습니다: {input_video_path}")

            ret, prev_frame = cap.read()
            if not ret:
                cap.release()
                if temp_video_path and temp_video_path.exists():
                    temp_video_path.unlink()
                raise RuntimeError("재인코딩 후에도 첫 프레임을 읽을 수 없습니다")

        saved_paths = []
        last_sampled_frame_idx = -999999  # 충분히 작은 값
        frame_idx = 0

        # 첫 프레임 저장
        output_path = output_dir / f"frame_{frame_idx:06d}.{self.config.output_format}"
        resized = self.resize_frame(prev_frame)
        cv2.imwrite(
            str(output_path),
            resized,
            [cv2.IMWRITE_JPEG_QUALITY, self.config.output_quality]
        )
        saved_paths.append(output_path)
        self.stats['sampled_frames'] += 1
        last_sampled_frame_idx = frame_idx

        print(f"\n🔍 샘플링 시작...")

        while True:
            ret, current_frame = cap.read()
            if not ret:
                break

            frame_idx += 1

            # 진행 상황 콜백
            if progress_callback and frame_idx % 100 == 0:
                progress_callback(frame_idx, total_frames)

            # 최대 프레임 수 도달
            if max_frames and self.stats['sampled_frames'] >= max_frames:
                print(f"\n⚠️ 최대 프레임 수({max_frames})에 도달했습니다.")
                break

            # SSIM 계산
            ssim_score = self.calculate_ssim(prev_frame, current_frame)

            # 샘플링 여부 판단
            should_sample, reason = self.should_sample(
                frame_idx,
                last_sampled_frame_idx,
                ssim_score,
                fps
            )

            if should_sample:
                output_path = output_dir / f"frame_{frame_idx:06d}.{self.config.output_format}"
                resized = self.resize_frame(current_frame)
                cv2.imwrite(
                    str(output_path),
                    resized,
                    [cv2.IMWRITE_JPEG_QUALITY, self.config.output_quality]
                )
                saved_paths.append(output_path)
                self.stats['sampled_frames'] += 1
                last_sampled_frame_idx = frame_idx

                # 디버그 출력 (100개마다)
                if self.stats['sampled_frames'] % 100 == 0:
                    print(f"   샘플: {self.stats['sampled_frames']}개 "
                          f"(진행: {frame_idx / total_frames * 100:.1f}%, "
                          f"SSIM: {ssim_score:.3f}, 이유: {reason})")

            prev_frame = current_frame

        cap.release()

        # 임시 재인코딩 파일 정리
        if temp_video_path and temp_video_path.exists():
            print(f"🗑️ 임시 파일 삭제 중: {temp_video_path.name}")
            try:
                temp_video_path.unlink()
            except Exception as e:
                print(f"⚠️ 임시 파일 삭제 실패 (무시됨): {e}")

        print(f"\n✅ 샘플링 완료!")
        self.print_stats()

        return saved_paths

    def print_stats(self):
        """샘플링 통계 출력"""
        print(f"\n📊 샘플링 통계:")
        print(f"   - 총 프레임: {self.stats['total_frames']:,}개")
        print(f"   - 샘플링된 프레임: {self.stats['sampled_frames']:,}개")
        print(f"   - 샘플링 비율: {self.stats['sampled_frames'] / max(self.stats['total_frames'], 1) * 100:.2f}%")
        print(f"   - 잠수 구간 스킵: {self.stats['skipped_idle']:,}개")
        print(f"   - 장면 전환: {self.stats['scene_changes']:,}개")
        print(f"   - 주기 샘플링: {self.stats['interval_samples']:,}개")

    def save_metadata(self, output_dir: Path, input_video_path: Path):
        """메타데이터 저장"""
        metadata = {
            'input_video': str(input_video_path),
            'output_directory': str(output_dir),
            'timestamp': datetime.now().isoformat(),
            'config': {
                'ssim_high_threshold': self.config.ssim_high_threshold,
                'ssim_low_threshold': self.config.ssim_low_threshold,
                'interval_seconds': self.config.interval_seconds,
                'scene_change_threshold': self.config.scene_change_threshold,
            },
            'stats': self.stats
        }

        metadata_path = output_dir / "sampling_metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        print(f"\n💾 메타데이터 저장: {metadata_path}")


def main():
    parser = argparse.ArgumentParser(
        description="SSIM 기반 스마트 비디오 샘플링"
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
        '--max-frames',
        type=int,
        default=None,
        help="최대 샘플링 프레임 수 (기본: 무제한)"
    )
    parser.add_argument(
        '--ssim-high',
        type=float,
        default=0.98,
        help="SSIM 높은 임계값 (기본: 0.98)"
    )
    parser.add_argument(
        '--ssim-low',
        type=float,
        default=0.85,
        help="SSIM 낮은 임계값 (기본: 0.85)"
    )
    parser.add_argument(
        '--interval',
        type=float,
        default=5.0,
        help="주기 샘플링 간격 초 (기본: 5.0)"
    )
    parser.add_argument(
        '--resize-width',
        type=int,
        default=None,
        help="리사이즈 너비 (기본: 원본)"
    )
    parser.add_argument(
        '--quality',
        type=int,
        default=95,
        help="JPEG 품질 1-100 (기본: 95)"
    )

    args = parser.parse_args()

    # 설정 생성
    config = SamplingConfig(
        ssim_high_threshold=args.ssim_high,
        ssim_low_threshold=args.ssim_low,
        interval_seconds=args.interval,
        resize_width=args.resize_width,
        output_quality=args.quality
    )

    # 샘플러 생성
    sampler = VideoSampler(config)

    # 진행 상황 콜백
    def progress_callback(current, total):
        print(f"   진행: {current:,} / {total:,} ({current / total * 100:.1f}%)", end='\r')

    # 샘플링 실행
    try:
        saved_paths = sampler.sample_video(
            args.input,
            args.output,
            args.max_frames,
            progress_callback
        )

        print(f"\n✅ {len(saved_paths):,}개 프레임 저장 완료")
        print(f"   출력 디렉토리: {args.output}")

        # 메타데이터 저장
        sampler.save_metadata(args.output, args.input)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
