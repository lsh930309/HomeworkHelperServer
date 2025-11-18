#!/usr/bin/env python3
"""
Label Studio 비디오 라벨을 YOLO 형식으로 변환
비디오 타임라인 라벨 → 각 프레임 이미지 + YOLO txt 파일 생성

사용법:
    python label-studio/scripts/video_labels_to_yolo.py \
        --labels label-studio/data/export/project.json \
        --clips datasets/clips/ \
        --output datasets/labeled/
"""

import argparse
import json
import cv2
import shutil
from pathlib import Path
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass


@dataclass
class VideoLabel:
    """비디오 라벨 정보"""
    video_file: str
    start_frame: int
    end_frame: int
    x: float  # 정규화된 좌표 (0-100)
    y: float
    width: float
    height: float
    label: str


@dataclass
class ConversionConfig:
    """변환 설정"""
    train_ratio: float = 0.8
    val_ratio: float = 0.15
    test_ratio: float = 0.05
    frame_interval: int = 1  # 프레임 추출 간격 (1=모든 프레임)
    output_format: str = "jpg"
    quality: int = 95


class VideoLabelsToYOLO:
    """Label Studio 비디오 라벨 → YOLO 변환기"""

    def __init__(self, class_mapping_path: Path, config: ConversionConfig = None):
        self.config = config or ConversionConfig()
        self.class_mapping = self._load_class_mapping(class_mapping_path)
        self.stats = {
            'total_videos': 0,
            'total_frames': 0,
            'total_labels': 0,
            'train_images': 0,
            'val_images': 0,
            'test_images': 0
        }

    def _load_class_mapping(self, path: Path) -> Dict[str, int]:
        """클래스 매핑 로드 (클래스명 → ID)"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        mapping = {}
        for cls in data['classes']:
            mapping[cls['name']] = cls['id']

        return mapping

    def parse_label_studio_json(self, json_path: Path) -> Dict[str, List[VideoLabel]]:
        """Label Studio JSON 파싱"""
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        video_labels = {}

        for task in data:
            if 'annotations' not in task or not task['annotations']:
                continue

            # 비디오 파일명
            video_file = task['data'].get('video', '')
            if not video_file:
                continue

            # 비디오 파일명만 추출 (URL이면)
            video_file = Path(video_file).name

            if video_file not in video_labels:
                video_labels[video_file] = []

            # 라벨 파싱
            for annotation in task['annotations']:
                for result in annotation.get('result', []):
                    if result['type'] != 'videorectangle':
                        continue

                    value = result['value']
                    labels = value.get('labels', [])

                    if not labels:
                        continue

                    # 타임라인 정보
                    start = value.get('start', 0)
                    duration = value.get('duration', 0)

                    # BBOX 좌표 (정규화된 %)
                    x = value.get('x', 0)
                    y = value.get('y', 0)
                    width = value.get('width', 0)
                    height = value.get('height', 0)

                    # 프레임으로 변환 (FPS는 나중에 비디오에서 가져옴)
                    label_obj = VideoLabel(
                        video_file=video_file,
                        start_frame=int(start),  # 초 단위를 나중에 프레임으로
                        end_frame=int(start + duration),
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                        label=labels[0]
                    )

                    video_labels[video_file].append(label_obj)

        return video_labels

    def convert_to_yolo_format(
        self,
        x: float, y: float, width: float, height: float
    ) -> Tuple[float, float, float, float]:
        """
        Label Studio 좌표 (%) → YOLO 형식 (중심점 + 크기, 정규화)

        Label Studio: (x, y, width, height) in %
        YOLO: (x_center, y_center, width, height) in 0-1
        """
        x_center = (x + width / 2) / 100
        y_center = (y + height / 2) / 100
        w_norm = width / 100
        h_norm = height / 100

        return x_center, y_center, w_norm, h_norm

    def extract_frames_with_labels(
        self,
        video_path: Path,
        labels: List[VideoLabel],
        output_dir: Path,
        split: str
    ) -> int:
        """
        비디오에서 프레임 추출 및 라벨 적용

        Args:
            video_path: 비디오 파일 경로
            labels: 해당 비디오의 라벨 리스트
            output_dir: 출력 디렉토리
            split: 'train', 'val', 'test'

        Returns:
            추출된 프레임 수
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            print(f"⚠️ 비디오를 열 수 없습니다: {video_path}")
            return 0

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # 초 → 프레임 변환
        for label in labels:
            label.start_frame = int(label.start_frame * fps)
            label.end_frame = int(label.end_frame * fps)

        # 출력 디렉토리
        images_dir = output_dir / split / 'images'
        labels_dir = output_dir / split / 'labels'
        images_dir.mkdir(parents=True, exist_ok=True)
        labels_dir.mkdir(parents=True, exist_ok=True)

        frame_count = 0
        video_name = video_path.stem

        for frame_idx in range(0, total_frames, self.config.frame_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()

            if not ret:
                break

            # 현재 프레임에 해당하는 라벨 찾기
            active_labels = [
                label for label in labels
                if label.start_frame <= frame_idx <= label.end_frame
            ]

            if not active_labels:
                continue  # 라벨이 없는 프레임은 건너뜀

            # 이미지 저장
            image_filename = f"{video_name}_frame_{frame_idx:06d}.{self.config.output_format}"
            image_path = images_dir / image_filename

            cv2.imwrite(
                str(image_path),
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, self.config.quality]
            )

            # YOLO 라벨 저장
            label_filename = f"{video_name}_frame_{frame_idx:06d}.txt"
            label_path = labels_dir / label_filename

            with open(label_path, 'w') as f:
                for label in active_labels:
                    class_id = self.class_mapping.get(label.label)
                    if class_id is None:
                        print(f"⚠️ 알 수 없는 클래스: {label.label}")
                        continue

                    # YOLO 형식 변환
                    x_center, y_center, w, h = self.convert_to_yolo_format(
                        label.x, label.y, label.width, label.height
                    )

                    f.write(f"{class_id} {x_center:.6f} {y_center:.6f} {w:.6f} {h:.6f}\n")

            frame_count += 1
            self.stats['total_labels'] += len(active_labels)

        cap.release()
        return frame_count

    def split_videos(self, video_files: List[Path]) -> Tuple[List[Path], List[Path], List[Path]]:
        """비디오를 train/val/test로 분할"""
        import random

        shuffled = list(video_files)
        random.shuffle(shuffled)

        total = len(shuffled)
        train_count = int(total * self.config.train_ratio)
        val_count = int(total * self.config.val_ratio)

        train_videos = shuffled[:train_count]
        val_videos = shuffled[train_count:train_count + val_count]
        test_videos = shuffled[train_count + val_count:]

        return train_videos, val_videos, test_videos

    def convert(
        self,
        labels_json: Path,
        clips_dir: Path,
        output_dir: Path
    ):
        """변환 실행"""
        print(f"📋 Label Studio 라벨 파싱 중...")
        video_labels = self.parse_label_studio_json(labels_json)

        if not video_labels:
            print("❌ 라벨을 찾을 수 없습니다.")
            return

        print(f"✅ {len(video_labels)}개 비디오의 라벨 파싱 완료")

        # 비디오 파일 찾기
        video_files = []
        for video_name in video_labels.keys():
            video_path = clips_dir / video_name
            if not video_path.exists():
                print(f"⚠️ 비디오 파일을 찾을 수 없습니다: {video_name}")
                continue
            video_files.append(video_path)

        self.stats['total_videos'] = len(video_files)

        # Train/Val/Test 분할
        print(f"\n📂 데이터셋 분할 중...")
        train_videos, val_videos, test_videos = self.split_videos(video_files)

        print(f"   - Train: {len(train_videos)}개")
        print(f"   - Val: {len(val_videos)}개")
        print(f"   - Test: {len(test_videos)}개")

        # 프레임 추출 및 라벨 생성
        print(f"\n🎬 프레임 추출 및 라벨 생성 중...")

        for video_path in train_videos:
            labels = video_labels[video_path.name]
            count = self.extract_frames_with_labels(video_path, labels, output_dir, 'train')
            self.stats['train_images'] += count
            print(f"   ✓ {video_path.name}: {count}개 프레임 (train)")

        for video_path in val_videos:
            labels = video_labels[video_path.name]
            count = self.extract_frames_with_labels(video_path, labels, output_dir, 'val')
            self.stats['val_images'] += count
            print(f"   ✓ {video_path.name}: {count}개 프레임 (val)")

        for video_path in test_videos:
            labels = video_labels[video_path.name]
            count = self.extract_frames_with_labels(video_path, labels, output_dir, 'test')
            self.stats['test_images'] += count
            print(f"   ✓ {video_path.name}: {count}개 프레임 (test)")

        self.stats['total_frames'] = (
            self.stats['train_images'] +
            self.stats['val_images'] +
            self.stats['test_images']
        )

        # data.yaml 생성
        self.create_data_yaml(output_dir)

        self.print_stats()

    def create_data_yaml(self, output_dir: Path):
        """YOLO data.yaml 생성"""
        yaml_content = f"""# HomeworkHelper YOLO Dataset
path: {output_dir.absolute()}
train: train/images
val: val/images
test: test/images

nc: {len(self.class_mapping)}
names:
"""

        # 클래스 ID 순서대로 정렬
        sorted_classes = sorted(self.class_mapping.items(), key=lambda x: x[1])
        for class_name, class_id in sorted_classes:
            yaml_content += f"  {class_id}: {class_name}\n"

        yaml_path = output_dir / "data.yaml"
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)

        print(f"\n💾 data.yaml 생성: {yaml_path}")

    def print_stats(self):
        """통계 출력"""
        print(f"\n📊 변환 통계:")
        print(f"   - 총 비디오: {self.stats['total_videos']}개")
        print(f"   - 총 프레임: {self.stats['total_frames']:,}개")
        print(f"   - 총 라벨: {self.stats['total_labels']:,}개")
        print(f"   - Train: {self.stats['train_images']:,}개")
        print(f"   - Val: {self.stats['val_images']:,}개")
        print(f"   - Test: {self.stats['test_images']:,}개")


def main():
    parser = argparse.ArgumentParser(
        description="Label Studio 비디오 라벨 → YOLO 변환"
    )
    parser.add_argument(
        '--labels',
        type=Path,
        required=True,
        help="Label Studio export JSON 파일"
    )
    parser.add_argument(
        '--clips',
        type=Path,
        required=True,
        help="비디오 클립 디렉토리"
    )
    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help="출력 디렉토리"
    )
    parser.add_argument(
        '--class-mapping',
        type=Path,
        default=Path('label-studio/config/class-mapping.json'),
        help="클래스 매핑 JSON 파일"
    )
    parser.add_argument(
        '--train-ratio',
        type=float,
        default=0.8,
        help="Train 비율 (기본: 0.8)"
    )
    parser.add_argument(
        '--val-ratio',
        type=float,
        default=0.15,
        help="Val 비율 (기본: 0.15)"
    )
    parser.add_argument(
        '--test-ratio',
        type=float,
        default=0.05,
        help="Test 비율 (기본: 0.05)"
    )
    parser.add_argument(
        '--frame-interval',
        type=int,
        default=1,
        help="프레임 추출 간격 (기본: 1=모든 프레임)"
    )

    args = parser.parse_args()

    # 설정 생성
    config = ConversionConfig(
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        frame_interval=args.frame_interval
    )

    # 변환기 생성
    converter = VideoLabelsToYOLO(args.class_mapping, config)

    try:
        converter.convert(args.labels, args.clips, args.output)
        print(f"\n✅ 변환 완료!")
        print(f"   출력 디렉토리: {args.output}")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
