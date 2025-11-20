#!/usr/bin/env python3
"""
데이터셋 분석 모듈
라벨링 데이터셋의 통계 및 정보 제공
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from collections import defaultdict


@dataclass
class DatasetStatistics:
    """데이터셋 통계"""
    total_images: int = 0
    total_videos: int = 0
    total_labels: int = 0
    labeling_complete_ratio: float = 0.0
    game_distribution: Dict[str, int] = None
    category_distribution: Dict[str, int] = None
    dataset_size_mb: float = 0.0

    def __post_init__(self):
        if self.game_distribution is None:
            self.game_distribution = {}
        if self.category_distribution is None:
            self.category_distribution = {}


class DatasetAnalyzer:
    """데이터셋 분석기"""

    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv'}
    LABEL_EXTENSIONS = {'.txt', '.xml', '.json'}

    def __init__(self, dataset_root: Optional[Path] = None):
        """
        데이터셋 분석기 초기화

        Args:
            dataset_root: 데이터셋 루트 디렉토리 (None이면 label-studio/datasets)
        """
        if dataset_root is None:
            from .utils import get_resource_path
            self.dataset_root = get_resource_path("datasets")
        else:
            self.dataset_root = dataset_root

    def analyze(self) -> DatasetStatistics:
        """
        데이터셋 분석 실행

        Returns:
            DatasetStatistics
        """
        stats = DatasetStatistics()

        if not self.dataset_root.exists():
            print(f"데이터셋 루트 디렉토리가 없습니다: {self.dataset_root}")
            return stats

        # 이미지/비디오 개수 카운트
        image_files = []
        video_files = []
        label_files = []

        for file_path in self.dataset_root.rglob('*'):
            if file_path.is_file():
                ext = file_path.suffix.lower()

                if ext in self.IMAGE_EXTENSIONS:
                    image_files.append(file_path)
                elif ext in self.VIDEO_EXTENSIONS:
                    video_files.append(file_path)
                elif ext in self.LABEL_EXTENSIONS:
                    label_files.append(file_path)

        stats.total_images = len(image_files)
        stats.total_videos = len(video_files)
        stats.total_labels = len(label_files)

        # 라벨링 완료율 계산
        # (이미지 파일 중 대응하는 라벨 파일이 있는 비율)
        labeled_images = self._count_labeled_images(image_files, label_files)
        if stats.total_images > 0:
            stats.labeling_complete_ratio = (labeled_images / stats.total_images) * 100

        # 게임별 분포 (디렉토리 이름 기반)
        stats.game_distribution = self._analyze_game_distribution(image_files)

        # 데이터셋 크기 계산
        stats.dataset_size_mb = self._calculate_size(self.dataset_root)

        return stats

    def _count_labeled_images(self, image_files: List[Path], label_files: List[Path]) -> int:
        """
        라벨링된 이미지 개수 카운트

        Args:
            image_files: 이미지 파일 리스트
            label_files: 라벨 파일 리스트

        Returns:
            라벨링된 이미지 개수
        """
        # 라벨 파일의 stem (확장자 제외 이름) 집합 생성
        label_stems = {lf.stem for lf in label_files}

        # 이미지 파일 중 대응하는 라벨이 있는 것 카운트
        labeled_count = 0
        for img_file in image_files:
            if img_file.stem in label_stems:
                labeled_count += 1

        return labeled_count

    def _analyze_game_distribution(self, image_files: List[Path]) -> Dict[str, int]:
        """
        게임별 이미지 분포 분석

        Args:
            image_files: 이미지 파일 리스트

        Returns:
            게임별 이미지 개수
        """
        distribution = defaultdict(int)

        # 게임 ID 키워드 (디렉토리 이름에서 검색)
        game_keywords = {
            "zenless": "Zenless Zone Zero",
            "honkai": "Honkai Star Rail",
            "wuthering": "Wuthering Waves",
            "nikke": "NIKKE"
        }

        for img_file in image_files:
            # 파일 경로에서 게임 추정
            path_str = str(img_file).lower()
            game_found = False

            for keyword, game_name in game_keywords.items():
                if keyword in path_str:
                    distribution[game_name] += 1
                    game_found = True
                    break

            if not game_found:
                distribution["Unknown"] += 1

        return dict(distribution)

    def _calculate_size(self, directory: Path) -> float:
        """
        디렉토리 크기 계산 (MB)

        Args:
            directory: 디렉토리 경로

        Returns:
            크기 (MB)
        """
        total_size = 0
        for file_path in directory.rglob('*'):
            if file_path.is_file():
                total_size += file_path.stat().st_size

        return total_size / (1024 * 1024)  # bytes to MB

    def get_file_tree(self, max_depth: int = 3) -> Dict:
        """
        데이터셋 파일 트리 반환 (GUI 트리뷰용)

        Args:
            max_depth: 최대 깊이

        Returns:
            파일 트리 딕셔너리
        """
        def build_tree(path: Path, depth: int = 0) -> Dict:
            if depth > max_depth:
                return {}

            tree = {
                'name': path.name,
                'path': str(path),
                'is_dir': path.is_dir(),
                'children': []
            }

            if path.is_dir():
                try:
                    for child in sorted(path.iterdir()):
                        tree['children'].append(build_tree(child, depth + 1))
                except PermissionError:
                    pass

            return tree

        if not self.dataset_root.exists():
            return {}

        return build_tree(self.dataset_root)

    def find_unlabeled_images(self) -> List[Path]:
        """
        라벨링되지 않은 이미지 찾기

        Returns:
            라벨링되지 않은 이미지 경로 리스트
        """
        if not self.dataset_root.exists():
            return []

        # 모든 이미지와 라벨 파일 찾기
        image_files = []
        label_files = []

        for file_path in self.dataset_root.rglob('*'):
            if file_path.is_file():
                ext = file_path.suffix.lower()
                if ext in self.IMAGE_EXTENSIONS:
                    image_files.append(file_path)
                elif ext in self.LABEL_EXTENSIONS:
                    label_files.append(file_path)

        # 라벨 파일 stem 집합
        label_stems = {lf.stem for lf in label_files}

        # 라벨 없는 이미지 필터링
        unlabeled = [
            img for img in image_files
            if img.stem not in label_stems
        ]

        return unlabeled

    def export_statistics(self, output_path: Path) -> bool:
        """
        통계를 JSON 파일로 내보내기

        Args:
            output_path: 출력 파일 경로

        Returns:
            성공 여부
        """
        try:
            stats = self.analyze()

            data = {
                'total_images': stats.total_images,
                'total_videos': stats.total_videos,
                'total_labels': stats.total_labels,
                'labeling_complete_ratio': stats.labeling_complete_ratio,
                'game_distribution': stats.game_distribution,
                'category_distribution': stats.category_distribution,
                'dataset_size_mb': stats.dataset_size_mb
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"통계 내보내기 완료: {output_path}")
            return True

        except Exception as e:
            print(f"통계 내보내기 실패: {e}")
            return False
