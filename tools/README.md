# 🛠️ HomeworkHelper 유틸리티 도구

MVP 개발을 위한 유틸리티 스크립트 모음

---

## 📋 도구 목록

### 1. 스키마 마이그레이션 (`migrate_schemas.py`)

**용도**: 기존 통합 JSON 파일을 게임별 디렉토리 구조로 분리

**실행 방법**:
```bash
python tools/migrate_schemas.py
```

**수행 작업**:
- ✅ 기존 파일 백업 (`schemas/old/`)
- ✅ 게임별 디렉토리 생성 (`schemas/games/{game_id}/`)
- ✅ 데이터 분리 (resources.json, contents.json, ui_elements.json)
- ✅ metadata.json 생성
- ✅ registry.json 생성

**출력**:
```
schemas/
├── registry.json
├── games/
│   ├── zenless_zone_zero/
│   │   ├── metadata.json
│   │   ├── resources.json
│   │   ├── contents.json
│   │   └── ui_elements.json
│   ├── honkai_star_rail/
│   ├── wuthering_waves/
│   └── nikke/
└── old/  (백업)
```

---

### 2. 한국어 명칭 검증 GUI (`schema_verifier_gui.py`)

**용도**: 게임 스키마의 한국어 명칭을 검증하고 수정하는 GUI 도구

**실행 방법**:
```bash
python tools/schema_verifier_gui.py
```

**주요 기능**:

#### 📝 항목별 편집
- **게임 선택**: 4개 게임 중 선택
- **타입 선택**: 재화 / 콘텐츠 / UI 요소
- **테이블 표시**: ID, 영어명, 한국어명, 검증 상태, 메모
- **편집 버튼**: 개별 항목 수정

#### ✅ 검증 기능
- **검증 완료 체크박스**: 한국어 명칭 확인 완료 표시
- **메모 추가**: 검증 관련 메모 작성
- **통계 표시**: 전체 항목 수 / 검증 완료 수

#### 💾 저장 및 관리
- **저장 버튼**: 수정사항 JSON 파일에 저장
- **새로고침 버튼**: 파일에서 다시 로드
- **모두 검증 완료**: 현재 표시된 모든 항목 일괄 검증

**스크린샷** (예상):
```
┌─────────────────────────────────────────────────────┐
│ 스키마 한국어 명칭 검증 도구                          │
├─────────────────────────────────────────────────────┤
│ 게임: [젠레스 존 제로 ▼]  타입: [재화 (Resources) ▼] │
│ 총 11개 항목 | 검증 완료: 0개 (0.0%)                 │
├─────────────────────────────────────────────────────┤
│ ID            │ 영어명      │ 한국어명 │ 검증 │ 메모 │
│ dennies       │ Dennies     │ 디니     │ ❌  │      │
│ polychrome    │ Polychrome  │ 폴리크롬 │ ❌  │      │
│ ...                                                  │
├─────────────────────────────────────────────────────┤
│ [모두 검증 완료]          [💾 저장] [🔄 새로고침]    │
└─────────────────────────────────────────────────────┘
```

**사용 워크플로우**:

1. **게임 선택**: 예) "젠레스 존 제로"
2. **타입 선택**: 예) "재화 (Resources)"
3. **항목 확인**: 테이블에서 한국어 명칭 확인
4. **편집 필요 시**:
   - ✏️ 편집 버튼 클릭
   - 한국어명 수정
   - 검증 완료 체크
   - 메모 작성 (선택)
   - OK 클릭
5. **저장**: 💾 저장 버튼 클릭
6. **다음 타입**: "콘텐츠 (Contents)" 선택 후 반복

**주의사항**:
- ⚠️ 저장하지 않고 게임/타입 변경 시 변경사항 손실
- ⚠️ 종료 시 저장 확인 알림

---

## 📦 의존성

두 스크립트 모두 다음 라이브러리를 사용합니다:

```bash
# 기본 라이브러리 (Python 3.11+)
- json
- pathlib
- sys

# PyQt6 (GUI 전용)
pip install PyQt6
```

---

## 🔧 향후 추가 예정 도구

### Week 1-2: 데이터 준비
- [ ] `video_sampler.py` - SSIM 기반 프레임 샘플링
- [ ] `scene_detector.py` - 장면 전환 감지
- [ ] `metadata_generator.py` - 비디오 메타데이터 생성

### Week 3: 라벨링
- [ ] `data_converter.py` - Label Studio → YOLO 형식 변환
- [ ] `label_validator.py` - 라벨 품질 검증

### Week 4-5: YOLO 학습
- [ ] `dataset_visualizer.py` - 데이터셋 시각화
- [ ] `training_monitor.py` - 학습 진행률 모니터링

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-11-14
