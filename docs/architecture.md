# HomeworkHelper MVP 아키텍처

**프로젝트**: HomeworkHelper - 게임 UI 탐지 및 자동화 시스템
**작성일**: 2025-11-14
**버전**: MVP v1.0

---

## 📑 목차

1. [프로젝트 개요](#-프로젝트-개요)
2. [개발 전략](#-개발-전략)
3. [시스템 아키텍처](#-시스템-아키텍처)
4. [기술 스택](#-기술-스택)
5. [프로젝트 구조](#-프로젝트-구조)
6. [데이터 플로우](#-데이터-플로우)
7. [개발 로드맵](#-개발-로드맵)

---

## 🎯 프로젝트 개요

### 핵심 문제
게임 플레이 중 UI 요소의 정보를 자동으로 수집하고 분석하고 싶지만, 다양한 해상도와 UI 설정에 따라 기존 OCR 방식이 실패하는 문제

### MVP 솔루션
**YOLO(객체 탐지) + OCR(텍스트 인식)** 하이브리드 방식으로 게임 UI 요소를 튼튼하게(Robust) 탐지하고 정보를 추출하는 시스템

### 주요 기능
1. **UI 요소 동적 탐지**: YOLO를 활용한 해상도 독립적 UI 위치 탐지
2. **텍스트 정보 추출**: 탐지된 영역에서 OCR로 재화/콘텐츠 정보 인식
3. **게임별 데이터 관리**: 게임별 재화, 콘텐츠, 숙제 목록 스키마 정의
4. **실시간 처리**: 게임 플레이 중 실시간 UI 분석 (100ms 이내)

### 목표 사용자
- 여러 게임의 일일 퀘스트를 관리하려는 게이머
- 게임 내 재화 및 콘텐츠 진행도를 자동으로 추적하려는 사용자

---

## 💡 개발 전략

### 로컬 우선 개발 (Local-First Development)
```
┌─────────────────────────────────────────────────────────┐
│  현재 전략: 로컬에서 프론트/백엔드 로직 분리 개발        │
│                                                          │
│  프론트엔드 로직 ──┬── 백엔드 로직                       │
│  (UI, 입력 처리)  │   (무거운 연산, YOLO, OCR)          │
│                   │                                      │
│                   └─► 향후 서버 분리 시 활용             │
│                       (배포 최후반에 진행)                │
└─────────────────────────────────────────────────────────┘
```

### 단계별 개발
1. **MVP Phase (현재)**: 로컬 프로토타입 완성
   - YOLO + OCR 파이프라인 구축
   - 게임 데이터 스키마 정의
   - 실시간 UI 탐지 시스템

2. **배포 Phase (최후반)**: 서버 분리 및 배포
   - 백엔드 로직을 서버로 이전
   - 클라우드/VM 배포
   - 멀티플랫폼 지원 (Android, iOS 등)

---

## 🏗️ 시스템 아키텍처

### 전체 시스템 구조

```
┌────────────────────────────────────────────────────────────────┐
│                    HomeworkHelper MVP System                    │
└────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                      로컬 애플리케이션                         │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌─────────────────┐         ┌─────────────────┐            │
│  │  프론트엔드      │         │  백엔드 로직     │            │
│  │  (PyQt6/Tkinter)│◄───────►│  (독립 모듈)    │            │
│  │                 │         │                 │            │
│  │ - UI 표시       │         │ - YOLO 추론     │            │
│  │ - 입력 처리     │         │ - OCR 처리      │            │
│  │ - 데이터 시각화 │         │ - 데이터 가공   │            │
│  └─────────────────┘         └────────┬────────┘            │
│                                       │                      │
│                                       ▼                      │
│                              ┌─────────────────┐             │
│                              │  로컬 DB        │             │
│                              │  (SQLite)       │             │
│                              │                 │             │
│                              │ - 게임 데이터   │             │
│                              │ - 탐지 결과     │             │
│                              │ - 설정 정보     │             │
│                              └─────────────────┘             │
└──────────────────────────────────────────────────────────────┘
```

### YOLO + OCR 파이프라인

```
┌────────────────────────────────────────────────────────────┐
│              UI 탐지 및 텍스트 추출 파이프라인               │
└────────────────────────────────────────────────────────────┘

게임 화면 캡처 (Screenshot)
         │
         ▼
┌─────────────────────┐
│   전처리             │
│   - 리사이징 (640px) │
│   - 정규화           │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   YOLO 추론         │
│   - UI 요소 탐지     │
│   - BBOX 좌표 출력   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   BBOX 영역 크롭    │
│   - 탐지된 영역 추출 │
│   - 개별 이미지 생성 │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   OCR 전처리        │
│   - 그레이스케일     │
│   - 이진화           │
│   - 노이즈 제거      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   OCR 엔진          │
│   - 텍스트 추출      │
│   - 신뢰도 점수      │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   후처리             │
│   - 정규표현식 파싱  │
│   - 숫자 추출        │
│   - 검증             │
└──────────┬──────────┘
           │
           ▼
    구조화된 데이터
    (JSON)
```

---

## 🛠️ 기술 스택

### 개발 환경
- **언어**: Python 3.11+
- **OS**: Windows 10/11 (개발), Ubuntu 22.04 (향후 서버)
- **GPU**: NVIDIA GTX 1060+ (6GB VRAM, CUDA 11.8+)

### 핵심 라이브러리

#### AI/ML
- **객체 탐지**: `ultralytics` (YOLOv8)
- **OCR**: `pytesseract`, `easyocr`, `paddleocr`
- **이미지 처리**: `opencv-python`, `PIL/Pillow`

#### 프론트엔드
- **GUI**: `PyQt6` 또는 `Tkinter`
- **시각화**: `matplotlib`, `plotly`

#### 백엔드
- **웹 프레임워크**: `FastAPI` (향후 서버 분리 시)
- **데이터베이스**: `SQLite` (로컬), `PostgreSQL` (향후 서버)
- **ORM**: `SQLAlchemy`

#### 데이터 처리
- **비디오 처리**: `opencv-python`, `scikit-image`
- **데이터 관리**: `pandas`, `numpy`
- **직렬화**: `pydantic`, `json`

#### 개발 도구
- **라벨링**: Label Studio
- **버전 관리**: Git + Git LFS
- **패키징**: `PyInstaller` (배포용)

---

## 📁 프로젝트 구조

```
HomeworkHelperServer/
├── 📱 프론트엔드 (MVP)
│   ├── gui/
│   │   ├── main_window.py          # 메인 윈도우
│   │   ├── dialogs.py              # 대화상자 (게임 추가, 설정 등)
│   │   └── widgets.py              # 커스텀 위젯
│   │
│   └── assets/
│       ├── icons/                  # 아이콘 파일
│       └── styles/                 # CSS/QSS 스타일
│
├── 🧠 백엔드 로직 (MVP)
│   ├── core/
│   │   ├── yolo_detector.py        # YOLO 추론 엔진
│   │   ├── ocr_engine.py           # OCR 처리 엔진
│   │   └── pipeline.py             # YOLO + OCR 파이프라인
│   │
│   ├── data/
│   │   ├── database.py             # SQLite 연결 및 쿼리
│   │   ├── models.py               # SQLAlchemy 모델
│   │   └── schemas.py              # Pydantic 스키마
│   │
│   └── utils/
│       ├── image_utils.py          # 이미지 전처리
│       ├── screen_capture.py       # 화면 캡처 유틸리티
│       └── config.py               # 설정 관리
│
├── 🗂️ 게임 데이터 스키마
│   └── schemas/
│       ├── game_resources.json     # 재화 정의
│       ├── game_contents.json      # 콘텐츠 정의
│       └── ui_elements.json        # UI 요소 정의
│
├── 🤖 AI 모델
│   ├── models/
│   │   ├── yolo/
│   │   │   ├── best.pt             # 학습된 YOLO 모델
│   │   │   └── config.yaml         # 모델 설정
│   │   └── ocr/
│   │       └── (OCR 모델, 필요 시)
│   │
│   └── training/
│       ├── train.py                # YOLO 학습 스크립트
│       ├── data.yaml               # 데이터셋 설정
│       └── augmentation.py         # 데이터 증강
│
├── 🏷️ 라벨링 및 데이터셋
│   ├── label-studio/
│   │   ├── docker-compose.yml      # Label Studio 설정
│   │   └── config.xml              # 라벨링 템플릿
│   │
│   ├── datasets/
│   │   ├── raw/                    # 원본 이미지/비디오
│   │   ├── labeled/                # 라벨링 완료 데이터
│   │   └── processed/              # YOLO 형식 데이터셋
│   │
│   └── tools/
│       ├── video_sampler.py        # SSIM 기반 샘플링
│       └── data_converter.py       # Label Studio → YOLO 변환
│
├── 📚 문서
│   ├── docs/
│   │   ├── architecture.md         # 이 문서
│   │   ├── mvp-roadmap.md          # MVP 로드맵
│   │   ├── add_this_to_milestone.md # 마일스톤 상세
│   │   ├── git-workflow.md         # Git 워크플로우
│   │   └── archived/               # 보류된 문서
│   │
│   └── README.md                   # 프로젝트 소개
│
├── 🧪 테스트
│   └── tests/
│       ├── test_yolo.py            # YOLO 테스트
│       ├── test_ocr.py             # OCR 테스트
│       └── test_pipeline.py        # 파이프라인 테스트
│
└── ⚙️ 설정 및 의존성
    ├── requirements.txt            # Python 패키지
    ├── .gitignore                  # Git 제외 파일
    ├── .gitattributes              # Git LFS 설정
    └── pyproject.toml              # 프로젝트 메타데이터
```

---

## 🔄 데이터 플로우

### 1. 학습 단계 (Training Phase)

```
비디오 녹화 (게임 플레이)
    │
    ▼
SSIM 기반 스마트 샘플링
    │
    ▼
프레임 추출 (300-500장/30분)
    │
    ▼
Label Studio 라벨링
    │
    ▼
YOLO 형식 데이터셋 변환
    │
    ▼
YOLOv8 학습
    │
    ▼
모델 평가 및 최적화
    │
    ▼
최종 모델 저장 (best.pt)
```

### 2. 추론 단계 (Inference Phase)

```
게임 실행 중...
    │
    ▼
화면 캡처 (주기적 or 이벤트 기반)
    │
    ▼
YOLO 추론 → UI 요소 BBOX 탐지
    │
    ▼
BBOX 영역 크롭 및 전처리
    │
    ▼
OCR 엔진 → 텍스트 추출
    │
    ▼
후처리 및 검증
    │
    ▼
데이터 저장 (SQLite)
    │
    ▼
GUI 업데이트 (실시간 표시)
```

### 3. 데이터 저장 구조

```sql
-- 게임 정보
CREATE TABLE games (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    schema_path TEXT,  -- schemas/game_name.json
    created_at TIMESTAMP
);

-- 탐지 결과
CREATE TABLE detection_results (
    id INTEGER PRIMARY KEY,
    game_id INTEGER,
    timestamp TIMESTAMP,
    ui_element TEXT,  -- 'quest_hud', 'resource_gold', etc.
    bbox JSON,        -- [x, y, w, h]
    confidence FLOAT,
    ocr_text TEXT,
    parsed_value JSON,  -- 파싱된 데이터 (숫자, 상태 등)
    FOREIGN KEY (game_id) REFERENCES games(id)
);

-- 사용자 설정
CREATE TABLE settings (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE,
    value TEXT
);
```

---

## 🗺️ 개발 로드맵

### MVP Phase (4-6주)

#### Week 1-2: 데이터 준비
- [x] 게임별 데이터셋 스키마 정의
- [ ] 3개 해상도별 비디오 녹화 (16:9, 16:10, 21:9)
- [ ] SSIM 기반 스마트 샘플링 시스템 개발
- [ ] 1,000+ 프레임 추출 완료

#### Week 3: 라벨링
- [ ] Label Studio 환경 구축
- [ ] 라벨링 템플릿 설정
- [ ] 1,000+ BBOX 라벨링 완료
- [ ] 데이터셋 train/val/test 분리

#### Week 4-5: YOLO 학습
- [ ] YOLOv8 학습 환경 구성
- [ ] 1차 학습 (baseline, YOLOv8n)
- [ ] 2차 학습 (optimized, YOLOv8s)
- [ ] 모델 평가 (mAP@0.5 > 0.85)

#### Week 6: OCR 통합 및 완성
- [ ] OCR 엔진 벤치마크 (Tesseract, EasyOCR, PaddleOCR)
- [ ] YOLO + OCR 파이프라인 구현
- [ ] GUI 프로토타입 개발
- [ ] 엔드투엔드 테스트

### 향후 계획 (배포 Phase)

#### 서버 분리 (보류)
- 백엔드 로직을 FastAPI 서버로 분리
- PostgreSQL 데이터베이스 마이그레이션
- Docker 컨테이너화

#### 클라우드 배포 (보류)
- AWS/GCP/Azure 배포
- CI/CD 파이프라인 구축
- 모니터링 시스템 (Prometheus, Grafana)

#### 멀티플랫폼 (보류)
- Android 앱 개발
- iOS 앱 개발 (선택)
- 웹 대시보드

---

## 📊 성능 목표

### MVP 성공 기준

| 항목 | 목표 | 현재 상태 |
|------|------|----------|
| UI 탐지 정확도 (mAP@0.5) | > 0.85 | - |
| OCR 정확도 | > 90% | - |
| 처리 속도 (프레임당) | < 100ms | - |
| 지원 해상도 | 3+ (16:9, 16:10, 21:9) | - |
| 지원 게임 | 1+ (프로토타입) | - |

---

## 🔗 관련 문서

- **[MVP 로드맵](./mvp-roadmap.md)**: 상세 개발 일정 및 마일스톤
- **[마일스톤 상세](./add_this_to_milestone.md)**: YOLO + OCR 구현 계획
- **[Git 워크플로우](./git-workflow.md)**: 브랜치 전략 및 커밋 규칙
- **[개발 환경 설정](./dev-setup-guide.md)**: 멀티 PC 개발 환경 가이드

---

## 📝 변경 이력

| 날짜 | 버전 | 변경 내용 |
|------|------|-----------|
| 2025-11-14 | MVP v1.0 | 초기 MVP 아키텍처 문서 작성 |

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-11-14
