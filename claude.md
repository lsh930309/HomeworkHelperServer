# HomeworkHelper MVP 개발 진행 상황

**작성일**: 2025-11-14
**현재 단계**: Phase 1 MVP - Week 1-2 데이터 준비
**브랜치**: `feature/dataset-schema`

---

## 📋 완료된 작업

### Week 1-2 Day 1-3: 게임별 데이터셋 스키마 정의 ✅

4개 게임에 대한 완전한 스키마 정의를 완료했습니다:
- 젠레스 존 제로 (Zenless Zone Zero)
- 붕괴: 스타레일 (Honkai: Star Rail)
- 명조: 워더링 웨이브 (Wuthering Waves)
- 승리의 여신: 니케 (Goddess of Victory: NIKKE)

#### 생성된 파일

**1. schemas/game_resources.json** (재화 정의)
- 젠레스 존 제로: 11개 재화
  - 디니(Dennies), 폴리크롬(Polychrome), 배터리(Battery Charge)
  - 마스터 테이프, 부스터 칩, 에테르 크리스탈 등
- 붕괴: 스타레일: 12개 재화
  - 성옥(Stellar Jade), 개척력(Trailblaze Power), 신용 포인트(Credit)
  - 별의 궤적, 여행자의 가이드, 운명의 발자취 등
- 워더링 웨이브: 11개 재화
  - 별조각(Astrite), 파동 플레이트(Waveplates), 쉘 크레딧(Shell Credit)
  - 광휘의 조수, 무기 강화 재료, 유니온 경험치 등
- 니케: 12개 재화
  - 보석(Gems), 전투 데이터 칩(Battle Data Chip), 크레딧(Credit)
  - 모집권, 코어 더스트, 스킬 매뉴얼, 바디 라벨 등

**스키마 특징**:
- OCR 패턴 정의 (정규표현식)
- 재화별 최대값 명시
- 카테고리 분류 (currency, premium_currency, stamina, material, special)

**2. schemas/game_contents.json** (콘텐츠 정의)
- 젠레스 존 제로: 7개 콘텐츠
  - 일일 의뢰, 루틴 정화, 전투 시뮬레이션, 제로호, 시유 방어전, 에테르 활동, 신호 탐색
- 붕괴: 스타레일: 10개 콘텐츠
  - 일일 임무, 칼릭스(황금/진홍), 응결 그림자, 침식 터널, 역경의 메아리
  - 시뮬레이션 우주, 혼돈의 기억, 순수 허구, 종말의 그림자
- 워더링 웨이브: 7개 콘텐츠
  - 일일 퀘스트, 단조 도전, 타짓 필드, 시뮬레이션 도전, 주간 보스, 역경의 탑, 환영의 심연
- 니케: 9개 콘텐츠
  - 일일 미션, 요격전, 시뮬레이션 룸, 전초기지, 트라이브 타워
  - 아레나, 루키 아레나, 솔로 레이드, 협동 레이드

**스키마 특징**:
- 리셋 시간 명시 (04:00, monday_04:00, biweekly 등)
- 진입 제한/스태미나 비용 정의
- 보상 목록 포함
- UI 인디케이터 참조 추가

**3. schemas/ui_elements.json** (UI 요소 정의 - YOLO 탐지 대상)
- 젠레스 존 제로: 22개 UI 요소
- 붕괴: 스타레일: 22개 UI 요소
- 워더링 웨이브: 21개 UI 요소
- 니케: 24개 UI 요소

**UI 요소 카테고리**:
- **hud**: 메인 HUD, 스태미나 표시기 등
- **quest**: 일일 퀘스트 HUD, 미션 목록 등
- **resource**: 재화 표시 (골드, 뽑기 재화 등)
- **content**: 던전/보스 진입 버튼
- **progress**: 층수 표시, 주간 횟수 표시 등
- **popup**: 보상 팝업, 알림창
- **button**: 메뉴 버튼, 뽑기 버튼 등
- **menu**: 캐릭터 메뉴, 상점 등

**스키마 특징**:
- YOLO 클래스명 명시 (예: `zzz_hud_main`, `hsr_quest_hud_daily`)
- OCR 타겟 지정 (contains_ocr: true/false, ocr_targets 배열)
- 화면 위치 정보 (typical_position)
- 항상 표시 여부 (always_visible)

---

## 🔧 Git 작업 내역

### 커밋 정보
- **브랜치**: `feature/dataset-schema` → `claude/dataset-schema-01UjMu2cvU6BwXD7sje58thR`
- **커밋 해시**: ba31011
- **커밋 메시지**: `feat: 게임별 데이터셋 스키마 정의 (Week 1-2, Day 1-3)`

### 변경 사항
```
3 files changed, 1900 insertions(+)
create mode 100644 schemas/game_contents.json
create mode 100644 schemas/game_resources.json
create mode 100644 schemas/ui_elements.json
```

### PR 생성
- **URL**: https://github.com/lsh930309/HomeworkHelperServer/pull/new/claude/dataset-schema-01UjMu2cvU6BwXD7sje58thR
- **상태**: 머지 대기 중

---

## 📊 스키마 통계

### 게임별 정의 수량

| 게임 | 재화 | 콘텐츠 | UI 요소 | 합계 |
|------|------|--------|---------|------|
| 젠레스 존 제로 | 11 | 7 | 22 | 40 |
| 붕괴: 스타레일 | 12 | 10 | 22 | 44 |
| 워더링 웨이브 | 11 | 7 | 21 | 39 |
| 니케 | 12 | 9 | 24 | 45 |
| **합계** | **46** | **33** | **89** | **168** |

### YOLO 클래스 수
- **총 89개 클래스** (게임별 21-24개)
- 모든 UI 요소는 고유한 YOLO 클래스명 보유
- 네이밍 규칙: `{게임ID}_{카테고리}_{요소명}`
  - 예: `zzz_hud_main`, `hsr_resource_stellar_jade`, `ww_tower_entry`, `nikke_mission_hud`

---

## 🎯 스키마 활용 계획

이 스키마들은 다음 단계에서 활용됩니다:

### Week 1-2 Day 4-7: 비디오 녹화 (다음 단계)
- `ui_elements.json`을 참고하여 89개 UI 요소가 모두 포함되도록 녹화
- 다양한 상황 캡처 (HUD 변화, 퀘스트 완료, 보상 팝업 등)

### Week 3: Label Studio 라벨링
- `ui_elements.json`의 `yolo_class_name` 사용
- 89개 클래스에 대한 BBOX 라벨링

### Week 4-5: YOLO 학습
- `data.yaml` 생성 시 클래스 정의 참조
- `nc: 89` (number of classes)
- `names: ['zzz_hud_main', 'zzz_battery_indicator', ...]`

### Week 6: OCR 통합
- `game_resources.json`의 `ocr_pattern` 사용하여 후처리
- 재화별 검증 (최대값 체크, 형식 검증)
- `game_contents.json`의 진행도 파싱

---

## 📝 다음 작업 (Week 1-2 Day 4-7)

### 비디오 녹화 준비
- [ ] 녹화 환경 설정
  - OBS Studio 또는 ShadowPlay 설치
  - 3개 해상도 환경 준비 (1920x1080, 2560x1600, 3440x1440)
- [ ] 게임별 30분+ 플레이 녹화
  - 모든 UI 요소가 화면에 나오도록 다양한 콘텐츠 플레이
  - 일일 퀘스트, 던전, 보스, 메뉴, 뽑기 등 포함
- [ ] 메타데이터 기록
  - `datasets/raw/metadata.json` 생성
  - 해상도, FPS, 게임 설정, 녹화 날짜 기록
- [ ] Git LFS 설정 (또는 외부 스토리지 업로드)

### 디렉토리 구조
```
datasets/raw/
  ├── 1920x1080/
  │   ├── zenless_zone_zero_session_01.mp4
  │   ├── honkai_star_rail_session_01.mp4
  │   ├── wuthering_waves_session_01.mp4
  │   ├── nikke_session_01.mp4
  │   └── metadata.json
  ├── 2560x1600/
  │   └── ...
  └── 3440x1440/
      └── ...
```

---

## 🔗 관련 문서

- **[아키텍처 가이드](docs/architecture.md)**: MVP 시스템 구조
- **[마일스톤 로드맵](docs/milestone.md)**: Phase 1-4 전체 계획
- **[MVP 로드맵](docs/mvp-roadmap.md)**: 주차별 상세 작업 내용
- **[Git 워크플로우](docs/git-workflow.md)**: 브랜치 전략

---

## ✅ 체크리스트

### Week 1-2: 데이터 준비
- [x] **Day 1-3: 스키마 정의** (완료)
  - [x] 게임 4개 선정
  - [x] game_resources.json 작성 (46개 재화)
  - [x] game_contents.json 작성 (33개 콘텐츠)
  - [x] ui_elements.json 작성 (89개 UI 요소)
  - [x] Git 커밋 및 푸시
- [ ] **Day 4-7: 비디오 녹화** (대기 중)
  - [ ] 3개 해상도별 녹화 환경 준비
  - [ ] 게임당 30분+ 플레이 영상 녹화
  - [ ] 메타데이터 기록
  - [ ] Git LFS 업로드
- [ ] **Day 8-14: 스마트 샘플링** (대기 중)
  - [ ] SSIM 기반 샘플링 스크립트 작성
  - [ ] 1,000+ 프레임 추출
  - [ ] 중복 프레임 검증

---

**작성자**: Claude (Sonnet 4.5)
**프로젝트**: HomeworkHelper MVP
**현재 진행률**: Week 1-2 중 Day 1-3 완료 (약 20%)
