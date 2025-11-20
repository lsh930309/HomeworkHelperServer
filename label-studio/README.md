# Label Studio 환경 구축

HomeworkHelper MVP 프로젝트의 YOLO 학습을 위한 라벨링 환경입니다.

## 🚀 빠른 시작

### 1. Label Studio 실행

```bash
cd label-studio
docker-compose up -d
```

### 2. 웹 인터페이스 접속

브라우저에서 http://localhost:8080 접속

**기본 로그인 정보**:
- Username: `admin`
- Password: `homework-helper-2025`

### 3. 프로젝트 생성

1. "Create Project" 클릭
2. 프로젝트 이름: `HomeworkHelper-UI-Detection`
3. "Labeling Setup" → "Object Detection with Bounding Boxes" 선택
4. 또는 `config/labeling-template.xml` 내용을 복사하여 Custom Template 사용

### 4. 이미지 업로드

1. 프로젝트 설정 → "Cloud Storage" 또는 "Import"
2. `datasets/processed/` 폴더의 이미지 업로드
3. 라벨링 시작!

---

## 📁 디렉토리 구조

```
label-studio/
├── docker-compose.yml       # Docker 설정
├── README.md                # 이 파일
├── config/
│   ├── labeling-template.xml   # Label Studio 라벨링 템플릿
│   └── class-mapping.json      # YOLO 클래스 매핑
├── data/                    # Label Studio 데이터 (Docker 볼륨)
│   ├── media/               # 업로드된 이미지
│   └── export/              # 라벨 내보내기
└── scripts/
    ├── generate_template.py    # 스키마에서 템플릿 자동 생성
    └── export_to_yolo.py       # Label Studio → YOLO 포맷 변환
```

---

## 🎯 비디오 라벨링 워크플로우

### 1. 비디오 세그멘테이션
```bash
# 원본 비디오를 안정된 클립으로 분할 (SSIM 기반)
python tools/video_segmenter.py --input datasets/raw/gameplay_30min.mp4 \
                                 --output datasets/clips/ \
                                 --min-duration 5 \
                                 --max-segments 20
```

### 2. Label Studio에 비디오 클립 업로드
- 웹 UI에서 "Import" → `datasets/clips/*.mp4` 선택
- 비디오 파일을 프로젝트에 추가

### 3. 비디오 타임라인 BBOX 라벨링
- 각 비디오 클립에서 UI 요소 시간 구간에 Bounding Box 그리기
- 타임라인 `[00:05 - 00:30]` 구간에 한 번만 라벨링 → 수백 프레임 자동 적용
- 올바른 클래스 선택 (예: `zzz_hud_main`, `zzz_quest_hud_daily`)
- 라벨 검증 및 저장

### 4. YOLO 형식으로 변환
```bash
# Label Studio 내보내기 (JSON)
# Project → Export → JSON 선택

# 비디오 라벨 → YOLO 형식 변환 (프레임 추출 + 라벨 적용)
python label-studio/scripts/video_labels_to_yolo.py \
    --labels label-studio/data/export/project-1.json \
    --clips datasets/clips/ \
    --output datasets/labeled/
```

---

## 🏷️ 라벨 클래스 목록

현재 지원하는 게임 및 UI 요소:

### Zenless Zone Zero (zzz)
- `zzz_hud_main` - 메인 HUD
- `zzz_battery_indicator` - 배터리 표시기
- `zzz_quest_hud_daily` - 일일 퀘스트 HUD
- ... (총 20+ 클래스)

### Honkai: Star Rail (hsr)
- `hsr_hud_main` - 메인 HUD
- `hsr_stamina_indicator` - 스태미나 표시기
- ... (총 20+ 클래스)

### Wuthering Waves (ww)
- `ww_hud_main` - 메인 HUD
- ... (총 20+ 클래스)

### NIKKE (nikke)
- `nikke_hud_main` - 메인 HUD
- ... (총 20+ 클래스)

**전체 클래스 목록**: `config/class-mapping.json` 참조

---

## 🛠️ 유틸리티 스크립트

### 1. 라벨링 템플릿 자동 생성

스키마 파일에서 Label Studio 템플릿 자동 생성:

```bash
python label-studio/scripts/generate_template.py
# 출력: label-studio/config/labeling-template.xml
```

### 2. YOLO 데이터셋 변환

```bash
python label-studio/scripts/export_to_yolo.py \
    --input label-studio/data/export/project-1-export.json \
    --output datasets/labeled/ \
    --train-ratio 0.8 \
    --val-ratio 0.15 \
    --test-ratio 0.05
```

생성 결과:
```
datasets/labeled/
├── train/
│   ├── images/
│   └── labels/
├── val/
│   ├── images/
│   └── labels/
├── test/
│   ├── images/
│   └── labels/
└── data.yaml  # YOLO 학습 설정
```

---

## 📊 라벨링 통계

라벨링 진행 상황 확인:

```bash
python label-studio/scripts/stats.py
```

출력 예시:
```
=== 라벨링 통계 ===
총 이미지: 1,000장
라벨링 완료: 850장 (85%)
클래스별 분포:
  - zzz_hud_main: 850개
  - zzz_battery_indicator: 820개
  - zzz_quest_hud_daily: 450개
  ...
```

---

## 🔧 트러블슈팅

### 문제: 포트 8080이 이미 사용 중

**해결**:
```bash
# docker-compose.yml 수정
ports:
  - "8081:8080"  # 다른 포트로 변경
```

### 문제: 이미지가 로드되지 않음

**해결**:
1. 이미지 경로 확인
2. Docker 볼륨 마운트 확인
3. Label Studio 재시작:
   ```bash
   docker-compose restart
   ```

### 문제: 라벨 데이터 손실

**해결**:
- `label-studio/data/` 폴더는 항상 백업
- Git에 커밋하지 말 것 (용량 큼)
- 정기적으로 Export 수행

---

## 📚 관련 문서

- [Label Studio 공식 문서](https://labelstud.io/guide/)
- [YOLO 데이터셋 포맷](https://docs.ultralytics.com/datasets/detect/)
- [MVP 로드맵](../docs/mvp-roadmap.md)

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-11-18
