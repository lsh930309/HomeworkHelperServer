#!/usr/bin/env python3
"""
스키마 파일에서 Label Studio 라벨링 템플릿 자동 생성
schemas/games/*/ui_elements.json 파일을 읽어서 YOLO 클래스 목록 추출
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any


def load_ui_elements_from_schema(game_id: str, schemas_dir: Path) -> List[Dict[str, Any]]:
    """게임 스키마에서 UI 요소 로드"""
    ui_elements_file = schemas_dir / "games" / game_id / "ui_elements.json"

    if not ui_elements_file.exists():
        print(f"⚠️ 스키마 파일 없음: {ui_elements_file}")
        return []

    with open(ui_elements_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        return data.get('ui_elements', [])


def collect_all_yolo_classes(schemas_dir: Path) -> Dict[str, List[Dict[str, str]]]:
    """모든 게임의 YOLO 클래스 수집"""
    registry_file = schemas_dir / "registry.json"

    if not registry_file.exists():
        print(f"❌ registry.json을 찾을 수 없습니다: {registry_file}")
        sys.exit(1)

    with open(registry_file, 'r', encoding='utf-8') as f:
        registry = json.load(f)

    all_classes = {}

    for game in registry['games']:
        if not game.get('enabled', True):
            continue

        game_id = game['game_id']
        game_name_kr = game.get('game_name_kr', game['game_name'])

        ui_elements = load_ui_elements_from_schema(game_id, schemas_dir)

        classes = []
        for element in ui_elements:
            yolo_class = element.get('yolo_class_name')
            name_kr = element.get('name_kr', element.get('name', ''))
            category = element.get('category', 'unknown')

            if yolo_class:
                classes.append({
                    'class_name': yolo_class,
                    'display_name': f"{name_kr} ({yolo_class})",
                    'name_kr': name_kr,
                    'category': category
                })

        if classes:
            all_classes[game_id] = {
                'game_name_kr': game_name_kr,
                'classes': classes
            }

    return all_classes


def generate_label_studio_xml(classes_by_game: Dict[str, List[Dict[str, str]]]) -> str:
    """Label Studio XML 템플릿 생성"""
    xml_lines = [
        '<View>',
        '  <Header value="HomeworkHelper UI Detection - YOLO 라벨링"/>',
        '  <Image name="image" value="$image" zoom="true" zoomControl="true" rotateControl="false"/>',
        '  ',
        '  <RectangleLabels name="label" toName="image" strokeWidth="2" smart="true">',
    ]

    # 게임별로 그룹화된 라벨 추가
    for game_id, game_data in classes_by_game.items():
        game_name = game_data['game_name_kr']
        classes = game_data['classes']

        xml_lines.append(f'    <!-- {game_name} ({game_id.upper()}) -->')

        # 카테고리별로 정렬
        categories = {}
        for cls in classes:
            cat = cls['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(cls)

        for category, cat_classes in sorted(categories.items()):
            if category != 'unknown':
                xml_lines.append(f'    <!-- {category.upper()} -->')

            for cls in cat_classes:
                display_name = cls['display_name']
                class_name = cls['class_name']
                # 색상은 카테고리별로 다르게
                color = get_color_for_category(category)
                xml_lines.append(f'    <Label value="{class_name}" background="{color}">{display_name}</Label>')

        xml_lines.append('')  # 게임 사이 빈 줄

    xml_lines.extend([
        '  </RectangleLabels>',
        '</View>'
    ])

    return '\n'.join(xml_lines)


def get_color_for_category(category: str) -> str:
    """카테고리별 색상 반환"""
    color_map = {
        'hud': '#FF6B6B',           # 빨강
        'quest': '#4ECDC4',         # 청록
        'menu': '#45B7D1',          # 파랑
        'popup': '#FFA07A',         # 주황
        'button': '#98D8C8',        # 민트
        'notification': '#FFD93D',  # 노랑
        'inventory': '#A8E6CF',     # 연두
        'character': '#C7CEEA',     # 보라
        'combat': '#FF8B94',        # 분홍
        'unknown': '#CCCCCC'        # 회색
    }
    return color_map.get(category, '#CCCCCC')


def generate_class_mapping_json(classes_by_game: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """YOLO 클래스 매핑 JSON 생성"""
    all_classes = []
    class_id = 0

    for game_id, game_data in classes_by_game.items():
        for cls in game_data['classes']:
            all_classes.append({
                'id': class_id,
                'name': cls['class_name'],
                'display_name': cls['display_name'],
                'name_kr': cls['name_kr'],
                'category': cls['category'],
                'game_id': game_id
            })
            class_id += 1

    return {
        'total_classes': len(all_classes),
        'classes': all_classes
    }


def main():
    # 프로젝트 루트 디렉토리 찾기
    current = Path(__file__).resolve().parent
    for _ in range(5):
        schemas_dir = current / "schemas"
        if schemas_dir.exists():
            break
        current = current.parent
    else:
        print("❌ schemas 디렉토리를 찾을 수 없습니다.")
        sys.exit(1)

    print("📂 스키마 디렉토리:", schemas_dir)

    # YOLO 클래스 수집
    print("\n🔍 YOLO 클래스 수집 중...")
    classes_by_game = collect_all_yolo_classes(schemas_dir)

    total_classes = sum(len(data['classes']) for data in classes_by_game.values())
    print(f"✅ 총 {total_classes}개 클래스 수집 완료")

    for game_id, data in classes_by_game.items():
        print(f"   - {data['game_name_kr']}: {len(data['classes'])}개")

    # Label Studio XML 템플릿 생성
    print("\n📝 Label Studio XML 템플릿 생성 중...")
    xml_template = generate_label_studio_xml(classes_by_game)

    config_dir = Path(__file__).parent.parent / "config"
    config_dir.mkdir(exist_ok=True)

    xml_output_path = config_dir / "labeling-template.xml"
    with open(xml_output_path, 'w', encoding='utf-8') as f:
        f.write(xml_template)

    print(f"✅ XML 템플릿 저장: {xml_output_path}")

    # 클래스 매핑 JSON 생성
    print("\n📊 클래스 매핑 JSON 생성 중...")
    class_mapping = generate_class_mapping_json(classes_by_game)

    json_output_path = config_dir / "class-mapping.json"
    with open(json_output_path, 'w', encoding='utf-8') as f:
        json.dump(class_mapping, f, ensure_ascii=False, indent=2)

    print(f"✅ 클래스 매핑 저장: {json_output_path}")

    print("\n✨ 템플릿 생성 완료!")
    print(f"\n사용 방법:")
    print(f"1. Label Studio 프로젝트 생성")
    print(f"2. Settings → Labeling Interface → Code")
    print(f"3. {xml_output_path} 내용 복사 & 붙여넣기")


if __name__ == '__main__':
    main()
