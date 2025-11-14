# 🚀 HomeworkHelper 프로젝트 마일스톤 로드맵

**프로젝트명**: HomeworkHelper
**최종 목표**: **PC/모바일 크로스 플랫폼** 지능형 게임 플레이 데이터 수집 및 예측 시스템
**최종 수정**: 2025-11-14
**버전**: v0.4 (MVP-First Strategy)

---

## 📊 프로젝트 비전

### 🎯 핵심 목표

**현재 (Phase 0)**: PC 전용 게임 루틴 관리 도구
**단기 (Phase 1 - MVP)**: YOLO + OCR 기반 게임 UI 탐지 엔진 v1.0
**장기 (Phase 4)**: PC/모바일 크로스 플랫폼 AI 기반 게임 데이터 수집 및 예측 서비스

### ⚡ MVP 전략

**기존 계획**: develop 브랜치에서 서버 아키텍처부터 구축 → 시간 과다 소요
**새로운 전략**: main 브랜치에서 YOLO + OCR MVP 프로토타입 빠르게 구축 → 이후 서버 개발

**MVP 핵심 문제**:
게임 해상도, 화면 비율, UI 설정 변경 시 기존 OCR의 정적 BBOX(좌표) 방식이 실패하는 문제

**MVP 솔루션**:
동적으로 변화하는 화면 환경에서도 핵심 UI 요소(예: 일일 임무 HUD, 재화 카운터)의 위치를 **튼튼하게(Robust)** 탐지하고, 그 안의 텍스트를 정확히 인식하는 프로토타입 시스템 구축

---

## 🏗️ 최종 목표 아키텍처 (Phase 4)

```
┌─────────────────────────────────────────────────────────────┐
│                     사용자 디바이스                           │
├─────────────────────────┬───────────────────────────────────┤
│   PC Client             │   Mobile Client                   │
│   (Ground-Truth)        │   (Event Logger)                  │
│                         │                                   │
│  • 화면 캡처 (mss)      │   • 게임 프로세스 감지            │
│  • YOLO UI 탐지         │   • 터치 이벤트 (선택)            │
│  • OCR 숫자 인식        │   • 타임스탬프 기록               │
│  • 정확한 자원 데이터   │   • 최소 배터리 소모              │
└──────────┬──────────────┴──────────┬────────────────────────┘
           │                         │
           └──────────┬──────────────┘
                      ▼
      ┌───────────────────────────────────────┐
      │        Cloud Backend (AI Brain)       │
      │  🔄 데이터 동기화 + 🧠 AI 예측         │
      └───────────────────────────────────────┘
```

**핵심 원칙**:
- **PC**: "정확한 데이터 수집기" (Heavy OCR)
- **모바일**: "경량 이벤트 로거" (Light Logger)
- **클라우드**: "AI 예측 및 동기화 중심" (Sync & AI)

---

## 📊 프로젝트 현황 요약

### ✅ 완료된 핵심 기능 (Phase 0)

1. **프로세스 모니터링 시스템**
   - psutil 기반 실시간 게임 프로세스 감지
   - 프로세스별 실행/종료 타임스탬프 자동 기록
   - 세션 기반 플레이 시간 트래킹

2. **알림 및 스케줄링**
   - 서버 리셋 시간 기반 알림
   - 사용자 주기 (24시간) 데드라인 추적
   - 필수 플레이 시간 알림
   - 수면 시간 보정 로직

3. **로컬 데이터 관리 시스템**
   - SQLite (WAL 모드) + SQLAlchemy ORM
   - FastAPI RESTful API 서버 (로컬)
   - 프로세스/세션/설정 CRUD 인터페이스

4. **빌드 및 배포 시스템**
   - PyInstaller onedir 모드 (MEI 폴더 문제 해결)
   - Inno Setup 인스톨러 자동화
   - daemon=True 설정으로 프로세스 종료 안정화

---

## 📅 단계별 마일스톤

---

## 🎯 Phase 1: MVP - 게임 UI 탐지 엔진 v1.0 (YOLO + OCR) ⭐ **현재 진행 중**

**목표**: 다양한 해상도/환경에서 동작하는 범용 UI 탐지 시스템 프로토타입 구축
**예상 기간**: 4-6주 (1인 개발 기준)
**핵심 기술**: YOLOv8, Tesseract/EasyOCR, Label Studio, SSIM
**난이도**: ⭐⭐⭐ (Medium) - CV + 데이터 처리 집중
**비용**: $0 (완전 로컬 환경)

### 1.1 데이터 준비 (1-2주)

#### 1.1.1 게임별 데이터셋 스키마 정의
- **작업**: `feature/dataset-schema`
- **산출물**:
  - `schemas/game_resources.json` - 재화 정의 (골드, 크리스탈, 스태미나 등)
  - `schemas/game_contents.json` - 콘텐츠 정의 (던전, 레이드, 퀘스트 등)
  - `schemas/ui_elements.json` - UI 요소 정의 (HUD, 메뉴, 팝업 등)
- **체크리스트**:
  - [ ] 3개 게임 이상 데이터셋 스키마 작성
  - [ ] 재화 항목 10개 이상 정의
  - [ ] UI 요소 20개 이상 정의

#### 1.1.2 비디오 데이터 수집
- **작업**: `feature/video-recording`
- **산출물**:
  - 해상도별 플레이 영상 (최소 3개 해상도)
    - `1920x1080 (16:9)` - 30분 이상
    - `2560x1600 (16:10)` - 30분 이상
    - `3440x1440 (21:9)` - 30분 이상
- **체크리스트**:
  - [ ] 각 해상도별 다양한 UI 상태 녹화
  - [ ] 전투, 메뉴, 인벤토리 등 다양한 씬 포함
  - [ ] 영상 메타데이터 기록 (해상도, FPS, 게임 설정)

#### 1.1.3 스마트 샘플링 시스템 개발
- **작업**: `feature/video-sampling`
- **산출물**:
  - `tools/video_sampler.py` - SSIM 기반 프레임 추출
  - `tools/scene_detector.py` - 장면 전환 감지
- **알고리즘**:
  ```python
  # SSIM 기반 스마트 샘플링
  - SSIM > 0.98 → Skip (잠수 구간)
  - SSIM < 0.85 → Save (유의미한 변화)
  - 0.85 ≤ SSIM ≤ 0.98 → Interval sampling (5초마다)
  ```
- **체크리스트**:
  - [ ] SSIM 임계값 튜닝 완료
  - [ ] 30분 영상에서 300-500 프레임 추출 검증
  - [ ] 중복 프레임 제거 확인

### 1.2 라벨링 시스템 구축 (1주)

#### 1.2.1 Label Studio 환경 설정
- **작업**: `feature/label-studio-setup`
- **산출물**:
  - `docker-compose.label-studio.yml`
  - `label-studio/config.xml` - 라벨링 템플릿
- **라벨링 스키마**:
  ```xml
  <RectangleLabels name="bbox" toName="image">
    <Label value="quest_hud_daily" />
    <Label value="quest_hud_complete" />
    <Label value="resource_gold" />
    <Label value="resource_crystal" />
    <Label value="menu_main" />
  </RectangleLabels>
  ```
- **체크리스트**:
  - [ ] Label Studio 로컬 서버 구동
  - [ ] 프로젝트 생성 및 템플릿 설정
  - [ ] 첫 10개 이미지 테스트 라벨링

#### 1.2.2 라벨링 작업
- **작업**: `feature/labeling-pipeline`
- **목표 데이터셋 크기**:
  - 훈련 데이터: 1,000+ 이미지
  - 검증 데이터: 200+ 이미지
  - 테스트 데이터: 100+ 이미지
- **라벨링 전략**:
  - 비디오 타임라인 기반 일괄 라벨링
  - `[01:30 ~ 01:35]` 구간에 동일 라벨 적용
- **체크리스트**:
  - [ ] 1,000개 이상 BBOX 라벨링 완료
  - [ ] 클래스별 균형 확인 (각 클래스 최소 50개)
  - [ ] 라벨 품질 검증 (샘플링 체크)

### 1.3 YOLO 모델 학습 (1-2주)

#### 1.3.1 학습 환경 구축
- **작업**: `feature/yolo-training-pipeline`
- **산출물**:
  - `training/train.py` - YOLOv8 학습 스크립트
  - `training/data.yaml` - 데이터셋 설정
  - `training/config.yaml` - 하이퍼파라미터 설정
- **하드웨어 요구사항**:
  - GPU: NVIDIA GTX 1060 이상 (6GB+ VRAM)
  - RAM: 16GB 이상
  - 디스크: 50GB+ 여유 공간
- **체크리스트**:
  - [ ] YOLOv8 설치 및 환경 구성
  - [ ] 데이터셋 YOLO 형식 변환
  - [ ] 학습/검증 데이터 분리 (80/20)

#### 1.3.2 모델 학습
- **작업**: `feature/model-training`
- **학습 계획**:
  ```python
  # 1차 학습: 베이스라인
  - Model: YOLOv8n (nano)
  - Epochs: 100
  - Batch size: 16
  - Image size: 640

  # 2차 학습: 성능 개선
  - Model: YOLOv8s (small)
  - Epochs: 200
  - Data augmentation 강화
  ```
- **체크리스트**:
  - [ ] 1차 학습 완료 (mAP@0.5 > 0.8)
  - [ ] 과적합 방지 (validation loss 모니터링)
  - [ ] 학습 로그 및 체크포인트 저장

#### 1.3.3 모델 평가
- **작업**: `feature/model-evaluation`
- **평가 지표**:
  - mAP@0.5 (Mean Average Precision)
  - Precision / Recall
  - Inference time (FPS)
- **테스트 시나리오**:
  - [ ] 훈련에 사용되지 않은 해상도 테스트
  - [ ] 다양한 밝기/대비 조건 테스트
  - [ ] 실시간 게임플레이 테스트
- **체크리스트**:
  - [ ] 테스트 데이터셋에서 mAP > 0.85
  - [ ] 오탐지율(False Positive) < 5%
  - [ ] 실시간 처리 속도 확인 (30 FPS 이상)

### 1.4 OCR 통합 및 시스템 완성 (1주)

#### 1.4.1 OCR 엔진 선정 및 통합
- **작업**: `feature/ocr-integration`
- **후보 OCR 엔진**:
  - Tesseract (오픈소스, 무료)
  - EasyOCR (딥러닝 기반, 높은 정확도)
  - PaddleOCR (중국어/한국어 강점)
- **통합 방식**:
  ```python
  # YOLO → OCR 파이프라인
  1. YOLO로 UI 요소 BBOX 탐지
  2. BBOX 영역 이미지 크롭
  3. 전처리 (그레이스케일, 이진화)
  4. OCR 엔진으로 텍스트 추출
  5. 후처리 (정규표현식, 숫자 파싱)
  ```
- **체크리스트**:
  - [ ] 3개 OCR 엔진 벤치마크 완료
  - [ ] 최적 OCR 엔진 선정
  - [ ] YOLO + OCR 파이프라인 구현

#### 1.4.2 엔드투엔드 테스트
- **작업**: `feature/ui-detection-test`
- **테스트 시나리오**:
  - [ ] 실시간 게임플레이에서 재화 정보 추출
  - [ ] 일일 퀘스트 진행도 자동 인식
  - [ ] 콘텐츠 완료 여부 판별
- **성능 목표**:
  - UI 탐지 정확도: 95% 이상
  - OCR 정확도: 90% 이상
  - 전체 처리 시간: 100ms 이내
- **체크리스트**:
  - [ ] 10회 이상 엔드투엔드 테스트 성공
  - [ ] 엣지 케이스 처리 (UI 가림, 애니메이션 등)
  - [ ] 에러 핸들링 로직 구현

### 1.5 Phase 1 MVP 성공 기준

- [ ] 3개 이상의 주요 해상도에서 95% 이상 UI 탐지 성공률
- [ ] 재화/콘텐츠 정보 OCR 정확도 90% 이상
- [ ] 실시간 처리 가능 (프레임당 100ms 이내)
- [ ] YOLO mAP@0.5 ≥ 0.85
- [ ] 학습된 모델 파일 < 10MB

**결과물**:
- YOLO 학습 데이터셋 (1,000+ 이미지)
- `game_ui_yolov8n.pt` (학습된 모델 파일)
- `yolo_detector.py` (YOLO + OCR 파이프라인)
- MVP 성능 리포트

---

## 🌐 Phase 2: 서버 아키텍처 + Android MVP + 클라우드 마이그레이션

**목표**: MVP를 기반으로 서버 아키텍처 구축 + Android 앱 개발 + 클라우드 배포
**예상 기간**: 4-5개월
**핵심 기술**: FastAPI, PostgreSQL, Docker, Android (Kotlin), AWS/GCP
**난이도**: ⭐⭐⭐⭐ (High) - 서버/모바일/클라우드 복합 작업

### 2.1 로컬 서버 아키텍처 구축

- **VM 환경 셋업 및 Docker 컨테이너 구축**
- **FastAPI 백엔드 개발** (세션, 이벤트, 동기화 API)
- **PostgreSQL 데이터베이스 스키마 설계**
- **JWT 인증 시스템**

### 2.2 Android 앱 MVP

- **Android 프로젝트 셋업** (Kotlin, MVVM)
- **게임 프로세스 모니터링** (UsageStatsManager)
- **서버 동기화 기능** (Retrofit)
- **알림 시스템**

### 2.3 클라우드 마이그레이션

- **클라우드 제공자 선택** (AWS/GCP/Vercel)
- **Docker 컨테이너 배포**
- **CI/CD 파이프라인** (GitHub Actions)
- **도메인 및 HTTPS 설정**

**결과물**:
- 클라우드 배포된 FastAPI 서버
- Android 앱 APK
- VM → 클라우드 마이그레이션 완료

---

## 🤖 Phase 3: AI 예측 모델 개발

**목표**: YOLO + OCR을 활용한 AI 행동 예측 모델 개발
**예상 기간**: 3-4개월
**핵심 기술**: XGBoost, 피처 엔지니어링, MLOps
**난이도**: ⭐⭐⭐⭐ (High) - ML + 데이터 파이프라인

### 3.1 수동 피드백 시스템 구축

- PC 클라이언트 세션 종료 시 피드백 수집
- 콘텐츠 타입 선택 UI

### 3.2 AI 모델 학습

- **Model 1**: 행동 분류 (XGBoost Classifier)
- **Model 2**: 자원 예측 (XGBoost Regressor)

### 3.3 클라우드 AI API 배포

- `/api/v1/predict` 엔드포인트
- PC/모바일 클라이언트 AI 예측 통합

**결과물**:
- AI 예측 모델 (정확도 ≥ 70%)
- 클라우드 AI API

---

## 📱 Phase 4: 모바일 앱 정식 출시 + VLM 보조 시스템

**목표**: 모바일 앱 완성 + VLM 기반 UI 변경 자동 대응
**예상 기간**: 6개월 이상
**핵심 기술**: React Native/Flutter, Claude Vision API, HoYoLAB
**난이도**: ⭐⭐⭐⭐⭐ (Very High)

### 4.1 모바일 앱 완성

- iOS 앱 개발
- 푸시 알림, 다크 모드, 다국어

### 4.2 VLM 기반 보정 시스템

- 게임 UI 업데이트 자동 감지
- VLM을 활용한 재보정

### 4.3 커뮤니티 기능

- 웹 대시보드
- 익명화된 데이터 공유

**결과물**:
- 앱스토어 정식 출시
- VLM 보정 시스템
- 5개 이상 게임 지원

---

## 📊 성공 지표 (KPI)

### Phase 1 (MVP) 성공 기준
- [ ] YOLO mAP@0.5 ≥ 0.85
- [ ] UI 탐지 정확도 ≥ 95% (3개 해상도)
- [ ] OCR 정확도 ≥ 90%
- [ ] 실시간 처리 속도 < 100ms

### Phase 2 성공 기준
- [ ] 클라우드 배포 완료 (Uptime ≥ 99%)
- [ ] Android 앱 서버 동기화 성공률 ≥ 95%

### Phase 3 성공 기준
- [ ] AI 행동 분류 정확도 ≥ 70%
- [ ] AI 자원 예측 MAE ≤ 20

### Phase 4 성공 기준
- [ ] 앱스토어 정식 출시
- [ ] 5개 이상 게임 지원
- [ ] 월간 활성 사용자 200명

---

## ⚠️ 리스크 및 대응 방안

### Phase 1 MVP 리스크

1. **라벨링 데이터 부족**
   - 대응: 데이터 증강(Augmentation) 활용

2. **GPU 메모리 부족**
   - 대응: 배치 크기 축소, 모델 경량화

3. **OCR 정확도 낮음**
   - 대응: 전처리 강화, 다중 OCR 엔진 앙상블

4. **실시간 처리 속도 느림**
   - 대응: 모델 경량화(YOLO nano), ONNX 변환

---

## 🔄 Phase 간 의존성

```
Phase 0 (완료) → Phase 1 (MVP 진행 중) → Phase 2 (서버) → Phase 3 (AI) → Phase 4 (완성)
                      ↓
                 YOLO + OCR 엔진
                      ↓
                 Phase 2-4의 핵심 기술 기반
```

---

## 📝 현재 액션 아이템 (Phase 1 MVP)

### 즉시 시작 가능한 작업

**Week 1-2: 데이터 준비**
- [ ] 게임별 데이터셋 스키마 정의
- [ ] 3개 해상도 영상 녹화
- [ ] 스마트 샘플링 시스템 개발
- [ ] 1,000+ 프레임 추출

**Week 3: 라벨링**
- [ ] Label Studio 환경 구축
- [ ] 1,000+ BBOX 라벨링

**Week 4-5: YOLO 학습**
- [ ] 학습 환경 구축
- [ ] 모델 학습 및 평가
- [ ] mAP@0.5 > 0.85 달성

**Week 6: OCR 통합**
- [ ] OCR 엔진 선정
- [ ] YOLO + OCR 파이프라인 구현
- [ ] 엔드투엔드 테스트

---

## 📚 참고 자료

### Phase 1 관련
- [YOLOv8 공식 문서](https://docs.ultralytics.com/)
- [Label Studio 공식 문서](https://labelstud.io/guide/)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- [EasyOCR](https://github.com/JaidedAI/EasyOCR)

### Phase 2 관련
- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [Docker 공식 문서](https://docs.docker.com/)
- [Android UsageStatsManager](https://developer.android.com/reference/android/app/usage/UsageStatsManager)

### Phase 3 관련
- [XGBoost 공식 문서](https://xgboost.readthedocs.io/)

### Phase 4 관련
- [Claude Vision API](https://docs.anthropic.com/claude/docs/vision)
- [GPT-4V API](https://platform.openai.com/docs/guides/vision)

---

## 📌 마일스톤 관리

### 업데이트 이력
- **v0.1 (2025-10-27)**: 초기 로드맵 작성 (PC 중심)
- **v0.2 (2025-10-27)**: 크로스 플랫폼 아키텍처 전면 수정
- **v0.3 (2025-10-27)**: Phase 1 로컬 환경 중심으로 재구성
- **v0.4 (2025-11-14)**: MVP 전략 반영 및 문서 구조 전면 개편
  - Phase 1을 YOLO + OCR MVP로 완전 교체
  - 서버 개발을 Phase 2로 이동
  - add_this_to_milestone.md 내용 통합
  - 4-6주 단기 MVP 로드맵 반영

### 다음 리뷰 예정일
- **Phase 1 MVP 완료 시** (2025년 12월 말 예상): Phase 2 서버 개발 상세 계획 업데이트

---

## 🎯 프로젝트 성공을 위한 핵심 원칙

1. **MVP First**: 완벽한 시스템보다 빠른 프로토타입 + 지속 개선
2. **데이터 품질 > 속도**: AI 모델은 데이터 품질에 좌우됨
3. **로컬 우선 개발**: 서버는 나중에, 먼저 로컬에서 작동하는 시스템 구축
4. **점진적 확장**: Phase 1 MVP → Phase 2 서버 → Phase 3 AI → Phase 4 완성

---

**작성자**: HomeworkHelper Development Team
**최종 수정**: 2025-11-14
**문서 버전**: v0.4 (MVP-First Strategy)

**다음 목표**: Phase 1 MVP (YOLO + OCR 엔진) 4-6주 내 완성 🚀
