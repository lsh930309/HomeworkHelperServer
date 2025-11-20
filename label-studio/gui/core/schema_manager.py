#!/usr/bin/env python3
"""
스키마 관리 모듈
Label Studio 클래스 매핑 (class-mapping.json) CRUD 작업
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict


@dataclass
class SchemaClass:
    """스키마 클래스 정의"""
    id: int
    name: str
    display_name: str
    name_kr: str
    category: str
    game_id: str

    def __post_init__(self):
        """타입 변환"""
        self.id = int(self.id)


class SchemaManager:
    """스키마 관리자"""

    GAME_IDS = {
        "zenless_zone_zero": "젠레스 존 제로",
        "honkai_star_rail": "붕괴: 스타레일",
        "wuthering_waves": "명조",
        "nikke": "승리의 여신: 니케"
    }

    CATEGORIES = {
        "hud": "HUD",
        "quest": "퀘스트",
        "button": "버튼",
        "resource": "재화",
        "content": "콘텐츠",
        "notification": "알림",
        "popup": "팝업",
        "gacha": "뽑기",
        "event": "이벤트",
        "progress": "진행도",
        "menu": "메뉴"
    }

    def __init__(self, class_mapping_path: Optional[Path] = None):
        """
        스키마 관리자 초기화

        Args:
            class_mapping_path: class-mapping.json 파일 경로
        """
        if class_mapping_path is None:
            # 기본 경로: label-studio/config/class-mapping.json
            self.class_mapping_path = Path(__file__).parent.parent.parent / "config" / "class-mapping.json"
        else:
            self.class_mapping_path = class_mapping_path

        self.classes: List[SchemaClass] = []
        self.load()

    def load(self) -> bool:
        """
        class-mapping.json 파일 로드

        Returns:
            성공 여부
        """
        if not self.class_mapping_path.exists():
            print(f"class-mapping.json 파일 없음: {self.class_mapping_path}")
            return False

        try:
            with open(self.class_mapping_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.classes = [
                SchemaClass(**cls_data)
                for cls_data in data.get('classes', [])
            ]

            print(f"스키마 로드 완료: {len(self.classes)}개 클래스")
            return True

        except Exception as e:
            print(f"스키마 로드 실패: {e}")
            return False

    def save(self) -> bool:
        """
        class-mapping.json 파일 저장

        Returns:
            성공 여부
        """
        try:
            data = {
                "total_classes": len(self.classes),
                "classes": [
                    asdict(cls)
                    for cls in self.classes
                ]
            }

            with open(self.class_mapping_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"스키마 저장 완료: {len(self.classes)}개 클래스")
            return True

        except Exception as e:
            print(f"스키마 저장 실패: {e}")
            return False

    def get_all_classes(self) -> List[SchemaClass]:
        """모든 클래스 반환"""
        return self.classes.copy()

    def get_classes_by_game(self, game_id: str) -> List[SchemaClass]:
        """특정 게임의 클래스만 반환"""
        return [cls for cls in self.classes if cls.game_id == game_id]

    def get_class_by_id(self, class_id: int) -> Optional[SchemaClass]:
        """ID로 클래스 검색"""
        for cls in self.classes:
            if cls.id == class_id:
                return cls
        return None

    def get_class_by_name(self, name: str) -> Optional[SchemaClass]:
        """name으로 클래스 검색"""
        for cls in self.classes:
            if cls.name == name:
                return cls
        return None

    def add_class(self, new_class: SchemaClass) -> bool:
        """
        새 클래스 추가

        Args:
            new_class: 추가할 클래스

        Returns:
            성공 여부
        """
        # ID 중복 체크
        if self.get_class_by_id(new_class.id):
            print(f"ID {new_class.id}가 이미 존재합니다.")
            return False

        # name 중복 체크
        if self.get_class_by_name(new_class.name):
            print(f"name '{new_class.name}'이 이미 존재합니다.")
            return False

        self.classes.append(new_class)
        return self.save()

    def update_class(self, class_id: int, updated_class: SchemaClass) -> bool:
        """
        클래스 수정

        Args:
            class_id: 수정할 클래스 ID
            updated_class: 새 클래스 데이터

        Returns:
            성공 여부
        """
        for i, cls in enumerate(self.classes):
            if cls.id == class_id:
                self.classes[i] = updated_class
                return self.save()

        print(f"ID {class_id}인 클래스를 찾을 수 없습니다.")
        return False

    def delete_class(self, class_id: int) -> bool:
        """
        클래스 삭제

        Args:
            class_id: 삭제할 클래스 ID

        Returns:
            성공 여부
        """
        for i, cls in enumerate(self.classes):
            if cls.id == class_id:
                del self.classes[i]
                return self.save()

        print(f"ID {class_id}인 클래스를 찾을 수 없습니다.")
        return False

    def get_next_id(self) -> int:
        """다음 사용 가능한 ID 반환"""
        if not self.classes:
            return 0
        return max(cls.id for cls in self.classes) + 1

    def get_statistics(self) -> Dict[str, int]:
        """
        스키마 통계 반환

        Returns:
            게임별 클래스 개수
        """
        stats = {game_id: 0 for game_id in self.GAME_IDS.keys()}
        for cls in self.classes:
            if cls.game_id in stats:
                stats[cls.game_id] += 1

        return stats

    def get_category_statistics(self, game_id: Optional[str] = None) -> Dict[str, int]:
        """
        카테고리별 통계 반환

        Args:
            game_id: 특정 게임으로 필터 (None이면 전체)

        Returns:
            카테고리별 클래스 개수
        """
        classes = self.classes if game_id is None else self.get_classes_by_game(game_id)

        stats = {}
        for cls in classes:
            category = cls.category
            stats[category] = stats.get(category, 0) + 1

        return stats

    def search_classes(self, keyword: str, game_id: Optional[str] = None) -> List[SchemaClass]:
        """
        클래스 검색

        Args:
            keyword: 검색 키워드 (name, display_name, name_kr에서 검색)
            game_id: 특정 게임으로 필터 (None이면 전체)

        Returns:
            검색 결과 리스트
        """
        classes = self.classes if game_id is None else self.get_classes_by_game(game_id)

        keyword_lower = keyword.lower()
        results = []

        for cls in classes:
            if (keyword_lower in cls.name.lower() or
                keyword_lower in cls.display_name.lower() or
                keyword_lower in cls.name_kr.lower()):
                results.append(cls)

        return results

    def export_yolo_names(self, output_path: Path) -> bool:
        """
        YOLO 형식의 classes.txt 생성

        Args:
            output_path: 출력 파일 경로

        Returns:
            성공 여부
        """
        try:
            # ID 순으로 정렬
            sorted_classes = sorted(self.classes, key=lambda x: x.id)

            with open(output_path, 'w', encoding='utf-8') as f:
                for cls in sorted_classes:
                    f.write(f"{cls.name}\n")

            print(f"YOLO classes.txt 생성 완료: {output_path}")
            return True

        except Exception as e:
            print(f"YOLO classes.txt 생성 실패: {e}")
            return False
