# MVP 로드맵 (MVP Roadmap)

**프로젝트**: HomeworkHelper MVP
**작성일**: 2025-11-14
**버전**: v1.0

---

## 📋 목차

1. [전체 타임라인](#-전체-타임라인)
2. [주차별 상세 계획](#-주차별-상세-계획)
3. [마일스톤 정의](#-마일스톤-정의)
4. [체크리스트](#-체크리스트)
5. [리스크 관리](#-리스크-관리)

---

## 🗓️ 전체 타임라인

**MVP 개발 기간: 4-6주 (2025-11-14 ~ 2025-12-26)**

```mermaid
gantt
    title MVP 개발 타임라인
    dateFormat YYYY-MM-DD
    section Week 1-2: 데이터 준비
    스키마 정의           :d1, 2025-11-14, 3d
    비디오 녹화           :d2, after d1, 4d
    스마트 샘플링         :d3, after d2, 7d
    section Week 3: 라벨링
    Label Studio 구축     :d4, 2025-11-28, 2d
    BBOX 라벨링           :d5, after d4, 5d
    section Week 4-5: YOLO 학습
    학습 환경 구축        :d6, 2025-12-05, 3d
    1차 학습              :d7, after d6, 4d
    2차 학습              :d8, after d7, 4d
    모델 평가             :d9, after d8, 3d
    section Week 6: 완성
    OCR 통합              :d10, 2025-12-19, 3d
    GUI 프로토타입        :d11, after d10, 2d
    엔드투엔드 테스트     :d12, after d11, 2d
```

---

## 📅 주차별 상세 계획

### Week 1-2: 데이터 준비 (11/14 ~ 11/27)

#### Day 1-3: 게임별 데이터셋 스키마 정의 ✅
**브랜치**: `feature/dataset-schema` (완료)

**작업 내용**:
- [x] 4개 게임 선정 및 스키마 정의 완료
  - Zenless Zone Zero (22개 UI 클래스)
  - Honkai: Star Rail (22개 UI 클래스)
  - Wuthering Waves (21개 UI 클래스)
  - NIKKE (24개 UI 클래스)
- [x] 재화 항목 정의 완료
  - 게임별 `resources.json` 작성
  - 각 재화별 속성 정의 (이름, 타입, UI 위치 힌트)
- [x] 콘텐츠 항목 정의 완료
  - 게임별 `contents.json` 작성
  - 완료 조건, 보상 정의
- [x] UI 요소 정의 완료
  - 게임별 `ui_elements.json` 작성
  - **총 89개 YOLO 클래스 정의**

**산출물**:
```json
// schemas/game_resources.json 예시
{
  "game_name": "SampleGame",
  "resources": [
    {
      "id": "gold",
      "name": "골드",
      "type": "currency",
      "ui_hint": "top_right",
      "icon": "gold_icon.png"
    },
    ...
  ]
}
```

**완료 기준**: ✅
- 4개 게임 스키마 파일 작성 완료
- 총 89개 YOLO 클래스 정의
- main 브랜치에 merge 완료

---

#### Day 4-7: 비디오 녹화
**브랜치**: `feature/video-recording`

**작업 내용**:
- [ ] 녹화 설정 표준화
  - 해상도: `1920x1080 (16:9)`, `2560x1600 (16:10)`, `3440x1440 (21:9)`
  - FPS: 30 FPS 이상
  - 포맷: MP4 (H.264)
- [ ] 각 해상도별 30분 이상 플레이 영상 녹화
  - 다양한 UI 상태 포함 (전투, 메뉴, 인벤토리, 퀘스트 확인 등)
  - UI가 명확히 보이는 구간 위주 녹화
- [ ] 녹화 메타데이터 기록
  - `datasets/raw/metadata.json`
  - 해상도, FPS, 게임 설정, 녹화 날짜 등

**산출물**:
```
datasets/raw/
  ├── 1920x1080/
  │   ├── session_01.mp4 (30분+)
  │   └── metadata.json
  ├── 2560x1600/
  │   ├── session_01.mp4 (30분+)
  │   └── metadata.json
  └── 3440x1440/
      ├── session_01.mp4 (30분+)
      └── metadata.json
```

**완료 기준**:
- 3개 해상도별 30분+ 영상 녹화 완료
- 메타데이터 기록 완료
- Git LFS로 업로드 (또는 외부 스토리지)

---

#### Day 8-14: 비디오 세그멘테이션 시스템 개발 ✅
**브랜치**: `claude/check-work-progress-*` (완료)

**작업 내용**:
- [x] SSIM 기반 장면 분석 알고리즘 구현
  - `tools/video_segmenter.py` 작성 완료
  - OpenCV, scikit-image 활용
- [x] 스마트 세그멘테이션 로직 구현
  ```python
  # SSIM < 0.5 → 장면 전환 (새 세그먼트 시작)
  # 평균 SSIM > 0.95 → 안정 구간 (세그먼트 유지)
  # 5초 < 길이 < 60초 → 유효 세그먼트
  ```
- [x] 안정된 구간 자동 추출 기능
  - 로딩 화면, 애니메이션 자동 제거
  - UI가 일정한 구간만 선택
- [x] 세그멘테이션 파라미터 커스터마이징 지원
  - `--scene-threshold`, `--stability-threshold` 옵션 제공
  - `--min-duration`, `--max-duration` 조정 가능
- [x] 메타데이터 자동 저장
  - 세그먼트 통계 및 설정 기록

**산출물**:
```
datasets/clips/
  ├── segment_001.mp4  (30초 - 전투 화면)
  ├── segment_002.mp4  (45초 - 메뉴 화면)
  ├── segment_003.mp4  (20초 - 퀘스트 화면)
  └── segments_metadata.json

Total: 10-20개 비디오 클립 (5-10분 분량)
```

**완료 기준**: ✅
- 세그멘테이션 스크립트 동작 확인 완료
- CLI 인터페이스 완성
- 안정 구간 감지 로직 검증 완료
- 문서화 완료 (tools/README.md, docs/workflows/video-labeling-workflow.md)

---

### Week 3: 라벨링 (11/28 ~ 12/04)

#### Day 15-16: Label Studio 환경 구축 ✅
**브랜치**: `claude/check-work-progress-*` (완료)

**작업 내용**:
- [x] Label Studio Docker 설정
  - `label-studio/docker-compose.yml` 작성 완료
  - 로컬 서버 실행 설정 (http://localhost:8080)
- [x] 라벨링 템플릿 자동 생성
  - `label-studio/scripts/generate_template.py` 구현
  - 스키마에서 **89개 클래스** 자동 수집
  - `label-studio/config/labeling-template.xml` 생성
  - 카테고리별 색상 구분
- [x] Windows 원클릭 실행 배치 파일
  - `start-label-studio.bat` - 시작 + 브라우저 자동 열림
  - `stop-label-studio.bat` - 중지
  - `open-label-studio.bat` - 브라우저만 열기
  - `view-label-studio-logs.bat` - 로그 확인
- [x] 상세 사용 가이드 작성
  - `README-LABEL-STUDIO.md` - 6단계 워크플로우
  - 문제 해결 가이드 포함

**산출물**:
- Label Studio 프로젝트 설정 파일
- 테스트 라벨링 결과 (10장)

**완료 기준**: ✅
- Label Studio 정상 동작 확인
- 89개 YOLO 클래스 템플릿 생성 완료
- Windows 사용자 친화적 실행 환경 구축
- 문서화 완료

---

#### Day 17-21: 라벨링 작업
**브랜치**: `feature/labeling-pipeline`

**작업 내용**:
- [ ] 10-20개 비디오 클립 타임라인 BBOX 라벨링
  - 비디오 타임라인 기반 일괄 라벨링 활용
  - `[00:05 ~ 00:30]` 구간에 한 번만 라벨링 → 수백 프레임 자동 적용
  - 라벨링 시간: 클립당 평균 1-2분 (총 15-30분 작업)
- [ ] 라벨 품질 관리
  - 각 클립의 첫 프레임 샘플링 검증
  - 클래스별 균형 확인 (각 클래스 최소 50개 프레임)
- [ ] 비디오 라벨 → YOLO 형식 변환
  - `label-studio/scripts/video_labels_to_yolo.py` 사용
  - 프레임 추출 + YOLO txt 파일 생성
  - Train/Val/Test 자동 분할 (80%/15%/5%)

**산출물**:
```
datasets/labeled/
  ├── train/
  │   ├── images/
  │   │   ├── segment001_frame_000000.jpg
  │   │   ├── segment001_frame_000001.jpg
  │   │   └── ... (8,000+장)
  │   └── labels/
  │       ├── segment001_frame_000000.txt (YOLO format)
  │       └── ...
  ├── val/
  │   ├── images/ (1,500+장)
  │   └── labels/
  └── test/
      ├── images/ (500+장)
      └── labels/

data.yaml:
  train: datasets/labeled/train/images
  val: datasets/labeled/val/images
  test: datasets/labeled/test/images
  nc: 89  # number of classes (4개 게임 전체)
  names: ['zzz_hud_main', 'zzz_quest_hud_daily', ...]

Total: 10,000+ 프레임 (15-30분 라벨링 작업 → 10,000+ 학습 데이터)
```

**완료 기준**:
- 10-20개 비디오 클립 타임라인 라벨링 완료
- 10,000+ 프레임 YOLO 형식 데이터셋 생성
- data.yaml 작성 완료
- main 브랜치에 merge

---

### Week 4-5: YOLO 학습 (12/05 ~ 12/18)

#### Day 22-24: 학습 환경 구축
**브랜치**: `feature/yolo-training-pipeline`

**작업 내용**:
- [ ] YOLOv8 설치 및 환경 구성
  ```bash
  pip install ultralytics
  ```
- [ ] GPU 환경 확인
  - CUDA 11.8+ 설치 확인
  - PyTorch GPU 지원 확인
- [ ] 학습 스크립트 작성
  - `training/train.py`
  - `training/config.yaml` (하이퍼파라미터)
- [ ] 데이터셋 검증
  - 이미지/라벨 매칭 확인
  - 클래스 분포 확인

**산출물**:
```python
# training/train.py 예시
from ultralytics import YOLO

model = YOLO('yolov8n.pt')  # nano model
results = model.train(
    data='datasets/labeled/data.yaml',
    epochs=100,
    imgsz=640,
    batch=16,
    device=0  # GPU
)
```

**완료 기준**:
- YOLOv8 설치 및 동작 확인
- 학습 스크립트 테스트 성공 (1 epoch)
- main 브랜치에 merge

---

#### Day 25-28: 1차 학습 (Baseline)
**브랜치**: `feature/model-training-baseline`

**작업 내용**:
- [ ] YOLOv8n (nano) 모델 학습
  - Epochs: 100
  - Batch size: 16
  - Image size: 640
  - 데이터 증강: 기본값
- [ ] 학습 모니터링
  - TensorBoard 또는 Weights & Biases
  - Loss, mAP, Precision, Recall 추적
- [ ] 체크포인트 저장
  - 매 10 epoch마다 저장
  - Best 모델 자동 저장

**산출물**:
```
models/yolo/baseline/
  ├── weights/
  │   ├── best.pt  (mAP 최고 모델)
  │   └── last.pt  (마지막 epoch)
  ├── results/
  │   ├── confusion_matrix.png
  │   ├── F1_curve.png
  │   └── PR_curve.png
  └── logs/
      └── train.log
```

**완료 기준**:
- 100 epoch 학습 완료
- mAP@0.5 > 0.75 달성
- 과적합 없음 (val loss 안정적)

---

#### Day 29-32: 2차 학습 (Optimized)
**브랜치**: `feature/model-training-optimized`

**작업 내용**:
- [ ] YOLOv8s (small) 모델 학습
  - Epochs: 200
  - Batch size: 조정 (GPU 메모리에 따라)
  - Image size: 640
  - 데이터 증강 강화
    - Mosaic
    - MixUp
    - Random rotate, flip, scale
- [ ] 하이퍼파라미터 튜닝
  - Learning rate 조정
  - Weight decay 조정
- [ ] 앙상블 실험 (선택)

**산출물**:
```
models/yolo/optimized/
  ├── weights/
  │   └── best.pt  (최종 모델)
  └── results/
```

**완료 기준**:
- 200 epoch 학습 완료
- mAP@0.5 > 0.85 달성
- Inference time < 50ms (GPU)

---

#### Day 33-35: 모델 평가
**브랜치**: `feature/model-evaluation`

**작업 내용**:
- [ ] 테스트 데이터셋 평가
  - mAP@0.5, mAP@0.5:0.95
  - Precision, Recall, F1-score
- [ ] 해상도별 성능 테스트
  - 훈련에 사용되지 않은 해상도 포함
- [ ] 실시간 게임플레이 테스트
  - 실제 게임에서 UI 탐지 성공률 측정
- [ ] 오탐지 분석
  - False Positive 케이스 수집
  - 모델 개선 방안 도출

**산출물**:
```
models/yolo/evaluation/
  ├── test_results.json
  ├── error_analysis.md
  └── sample_predictions/
      ├── img_001_pred.jpg
      └── ...
```

**완료 기준**:
- 모든 평가 지표 달성
- 오탐지율 < 5%
- main 브랜치에 merge

---

### Week 6: OCR 통합 및 시스템 완성 (12/19 ~ 12/26)

#### Day 36-38: OCR 엔진 통합
**브랜치**: `feature/ocr-integration`

**작업 내용**:
- [ ] 3개 OCR 엔진 벤치마크
  - Tesseract
  - EasyOCR
  - PaddleOCR
  - 각 엔진의 정확도, 속도 비교
- [ ] 최적 OCR 엔진 선정
- [ ] YOLO + OCR 파이프라인 구현
  - `core/pipeline.py` 작성
  ```python
  def detect_and_extract(image):
      # 1. YOLO 추론
      bboxes = yolo_detector.detect(image)

      # 2. BBOX 크롭
      cropped_images = [crop(image, bbox) for bbox in bboxes]

      # 3. OCR 전처리
      preprocessed = [preprocess(img) for img in cropped_images]

      # 4. OCR 추론
      texts = [ocr_engine.extract(img) for img in preprocessed]

      # 5. 후처리
      parsed_data = [parse(text) for text in texts]

      return parsed_data
  ```
- [ ] 전처리/후처리 로직 구현
  - 그레이스케일, 이진화, 노이즈 제거
  - 정규표현식 파싱, 숫자 추출

**산출물**:
- OCR 벤치마크 결과 (accuracy, speed)
- 통합 파이프라인 코드

**완료 기준**:
- OCR 정확도 > 90%
- 전체 파이프라인 처리 시간 < 100ms
- main 브랜치에 merge

---

#### Day 39-40: GUI 프로토타입 개발
**브랜치**: `feature/gui-prototype`

**작업 내용**:
- [ ] 메인 윈도우 개발
  - PyQt6 또는 Tkinter
  - 화면 캡처 버튼
  - 실시간 결과 표시
- [ ] 결과 시각화
  - 탐지된 BBOX 표시
  - OCR 텍스트 표시
  - 파싱된 데이터 테이블
- [ ] 설정 대화상자
  - 게임 선택
  - 캡처 주기 설정
  - OCR 엔진 선택

**산출물**:
```
gui/
  ├── main_window.py
  ├── dialogs.py
  └── widgets.py
```

**완료 기준**:
- GUI 프로토타입 동작 확인
- 실시간 UI 탐지 및 OCR 표시
- main 브랜치에 merge

---

#### Day 41-42: 엔드투엔드 테스트
**브랜치**: `feature/e2e-test`

**작업 내용**:
- [ ] 10회 이상 실제 게임플레이 테스트
  - 재화 정보 추출 성공률
  - 일일 퀘스트 진행도 인식 성공률
  - 콘텐츠 완료 여부 판별 성공률
- [ ] 엣지 케이스 처리
  - UI 가림 (팝업, 애니메이션)
  - 밝기/대비 변화
  - 해상도 변경
- [ ] 에러 핸들링
  - 탐지 실패 시 재시도
  - OCR 신뢰도 낮을 시 경고
- [ ] 성능 최적화
  - 불필요한 연산 제거
  - 캐싱 적용

**산출물**:
- 테스트 결과 리포트
- 버그 수정 완료

**완료 기준**:
- 모든 성공 기준 달성
- MVP v1.0 릴리스

---

## 🎯 마일스톤 정의

### Milestone 1: 데이터 준비 완료 (Week 2 종료)
- ✅ 게임별 스키마 정의
- ✅ 비디오 녹화 완료
- ✅ 1,000+ 프레임 추출
- **Git Tag**: `mvp-v0.1-data-ready`

### Milestone 2: 라벨링 완료 (Week 3 종료)
- ✅ Label Studio 환경 구축
- ✅ 1,000+ BBOX 라벨링
- ✅ YOLO 형식 데이터셋 생성
- **Git Tag**: `mvp-v0.2-dataset-ready`

### Milestone 3: YOLO 학습 완료 (Week 5 종료)
- ✅ 1차 학습 (baseline)
- ✅ 2차 학습 (optimized)
- ✅ mAP@0.5 > 0.85 달성
- **Git Tag**: `mvp-v0.3-model-trained`

### Milestone 4: MVP 완성 (Week 6 종료)
- ✅ OCR 통합
- ✅ GUI 프로토타입
- ✅ 엔드투엔드 테스트 통과
- **Git Tag**: `mvp-v1.0`

---

## ✅ 체크리스트

### 데이터 준비
- [ ] 게임별 데이터셋 스키마 정의 완료
- [ ] 3개 이상 해상도별 영상 녹화 완료
- [ ] SSIM 기반 스마트 샘플링 구현
- [ ] 1,000+ 프레임 추출 완료

### 라벨링
- [ ] Label Studio 환경 구축
- [ ] 라벨링 템플릿 설정
- [ ] 1,000+ BBOX 라벨링 완료
- [ ] 데이터셋 train/val/test 분리

### 모델 학습
- [ ] YOLO 학습 환경 구축
- [ ] 1차 학습 완료 (baseline)
- [ ] 2차 학습 완료 (optimized)
- [ ] mAP@0.5 > 0.85 달성

### OCR 통합
- [ ] OCR 엔진 벤치마크 완료
- [ ] YOLO + OCR 파이프라인 구현
- [ ] 전처리/후처리 로직 구현
- [ ] OCR 정확도 90% 이상 달성

### 시스템 완성
- [ ] GUI 프로토타입 개발
- [ ] 엔드투엔드 테스트 통과
- [ ] 성능 최적화 (100ms 이내 처리)
- [ ] 에러 핸들링 구현
- [ ] 문서화 완료

---

## 🚧 리스크 관리

### 높은 우선순위 리스크

#### 1. 라벨링 데이터 부족
- **영향도**: 높음
- **발생 가능성**: 중간
- **대응 방안**:
  - 데이터 증강(Augmentation) 활용
  - 추가 비디오 녹화
  - 기존 라벨 재활용 (유사 UI 요소)

#### 2. OCR 정확도 낮음
- **영향도**: 높음
- **발생 가능성**: 중간
- **대응 방안**:
  - 전처리 알고리즘 개선
  - 다중 OCR 엔진 앙상블
  - 게임별 폰트 학습 (향후)

### 중간 우선순위 리스크

#### 3. GPU 메모리 부족
- **영향도**: 중간
- **발생 가능성**: 낮음
- **대응 방안**:
  - 배치 크기 축소
  - 모델 경량화 (YOLOv8n 사용)
  - Mixed precision training (FP16)

#### 4. 실시간 처리 속도 느림
- **영향도**: 중간
- **발생 가능성**: 중간
- **대응 방안**:
  - 모델 경량화 (YOLO nano)
  - ONNX 변환 및 최적화
  - GPU 가속 활용

### 낮은 우선순위 리스크

#### 5. 새 해상도 대응 실패
- **영향도**: 중간
- **발생 가능성**: 낮음
- **대응 방안**:
  - 다양한 해상도 데이터 추가 학습
  - 데이터 증강으로 해상도 변화 시뮬레이션

---

## 📊 진행 상황 추적

### 주차별 완료율

| Week | 계획 작업 | 완료 작업 | 진행률 | 상태 |
|------|----------|----------|--------|------|
| Week 1-2 | 데이터 준비 | Day 1-3: 스키마 정의 ✅<br>Day 8-14: SSIM 샘플링 ✅ | 40% | 🚧 진행 중 |
| Week 3 | 라벨링 | Day 15-16: Label Studio 구축 ✅ | 33% | 🚧 진행 중 |
| Week 4-5 | YOLO 학습 | - | 0% | ⏳ 대기 중 |
| Week 6 | OCR 통합 및 완성 | - | 0% | ⏳ 대기 중 |

### 전체 진행률
**~18% 완료** (8/42일)

---

## 🔗 관련 문서

- **[아키텍처](./architecture.md)**: 시스템 구조 및 기술 스택
- **[마일스톤 상세](./add_this_to_milestone.md)**: YOLO + OCR 구현 계획
- **[Git 워크플로우](./git-workflow.md)**: 브랜치 전략 및 커밋 규칙

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-11-18
