# Pull Request: Label Studio 환경 구축 및 SSIM 기반 비디오 샘플링 구현

## 📋 작업 요약

MVP 개발을 위한 Label Studio 라벨링 환경 구축 및 SSIM 기반 스마트 비디오 샘플링 시스템 구현

---

## ✨ 주요 변경사항

### 1. Label Studio Docker 환경 구축 🏷️

**구현 내용**:
- Docker Compose 설정 (`label-studio/docker-compose.yml`)
- 89개 YOLO 클래스 자동 수집 (4개 게임)
  - Zenless Zone Zero: 22개
  - Honkai: Star Rail: 22개
  - Wuthering Waves: 21개
  - NIKKE: 24개

**자동화 스크립트**:
- `label-studio/scripts/generate_template.py`
  - 스키마에서 라벨링 템플릿 자동 생성
  - 카테고리별 색상 구분
  - 클래스 매핑 JSON 생성

**Windows 원클릭 실행**:
- `start-label-studio.bat` - Label Studio 시작 + 브라우저 자동 열림
- `stop-label-studio.bat` - Label Studio 중지
- `open-label-studio.bat` - 브라우저만 빠르게 열기
- `view-label-studio-logs.bat` - 실시간 로그 확인

**문서**:
- `README-LABEL-STUDIO.md` - 상세 사용 가이드 (6단계 워크플로우, 문제 해결)
- `label-studio/README.md` - Label Studio 설정 및 운영 가이드

---

### 2. SSIM 기반 스마트 비디오 샘플링 📹

**구현 내용**:
- `tools/video_sampler.py` - 완전 기능 구현
  - ✅ SSIM 기반 중복 프레임 제거 (> 0.98 스킵)
  - ✅ 장면 전환 감지 (< 0.5 즉시 저장)
  - ✅ 유의미한 변화 감지 (< 0.85 저장)
  - ✅ 주기 샘플링 (5초 간격)
  - ✅ 메타데이터 자동 저장 및 통계 출력

**알고리즘**:
```python
if SSIM < 0.5:       # 장면 전환
    save_frame()
elif SSIM < 0.85:    # 유의미한 변화
    save_frame()
elif SSIM > 0.98:    # 잠수 구간
    skip_frame()
else:                # 중간 구간
    interval_sample()  # 5초마다
```

**CLI 옵션**:
- `--max-frames` - 최대 샘플링 프레임 수
- `--ssim-high/low` - SSIM 임계값 커스터마이징
- `--interval` - 주기 샘플링 간격
- `--resize-width` - 리사이즈
- `--quality` - JPEG 품질

**문서**:
- `tools/README.md` - 비디오 샘플링 상세 가이드 추가
- `tools/requirements-mvp.txt` - MVP 개발 의존성 정의

---

### 3. 기타 개선사항

**스키마 수정**:
- `schemas/registry.json` - game_id를 디렉토리명과 일치
  - `zzz` → `zenless_zone_zero`
  - `hsr` → `honkai_star_rail`
  - `ww` → `wuthering_waves`

**Git 설정**:
- `.gitignore` - MVP 관련 디렉토리 추가
  - `label-studio/data/` (라벨링 데이터)
  - `datasets/` (비디오, 이미지, 라벨)
  - `models/yolo/` (학습 결과)

**문서 업데이트**:
- `README.md` - MVP 빠른 시작 섹션 추가
- `docs/mvp-roadmap.md` - 진행 상황 업데이트 (~18% 완료)

---

## 📁 새로운 파일

```
HomeworkHelperServer/
├── label-studio/
│   ├── docker-compose.yml          # Docker 설정
│   ├── README.md                   # 사용 가이드
│   ├── config/
│   │   ├── labeling-template.xml   # 89개 클래스 템플릿
│   │   └── class-mapping.json      # YOLO 클래스 매핑
│   └── scripts/
│       └── generate_template.py    # 자동 템플릿 생성
├── tools/
│   ├── video_sampler.py            # SSIM 샘플링
│   └── requirements-mvp.txt        # MVP 의존성
├── README-LABEL-STUDIO.md          # Label Studio 상세 가이드
├── start-label-studio.bat          # Windows 원클릭 시작
├── stop-label-studio.bat           # Label Studio 중지
├── open-label-studio.bat           # 브라우저 열기
└── view-label-studio-logs.bat      # 로그 확인
```

---

## 📊 MVP 로드맵 진행 상황

| Week | 완료 작업 | 진행률 | 상태 |
|------|----------|--------|------|
| Week 1-2 | Day 1-3: 스키마 정의 ✅<br>Day 8-14: SSIM 샘플링 ✅ | 40% | 🚧 진행 중 |
| Week 3 | Day 15-16: Label Studio 구축 ✅ | 33% | 🚧 진행 중 |
| Week 4-5 | - | 0% | ⏳ 대기 중 |
| Week 6 | - | 0% | ⏳ 대기 중 |

**전체 진행률**: ~18% (8/42일)

---

## 🚀 사용 방법

### Label Studio 시작
```bash
# Windows 탐색기에서 더블클릭
start-label-studio.bat
```
→ http://localhost:8080 (admin / homework-helper-2025)

### 비디오 샘플링
```bash
python tools/video_sampler.py \
    --input datasets/raw/your_video.mp4 \
    --output datasets/processed/output_dir/ \
    --max-frames 500
```

---

## 🔗 관련 문서

- [README-LABEL-STUDIO.md](README-LABEL-STUDIO.md) - Label Studio 상세 가이드
- [label-studio/README.md](label-studio/README.md) - Label Studio 설정
- [tools/README.md](tools/README.md) - 비디오 샘플링 가이드
- [docs/mvp-roadmap.md](docs/mvp-roadmap.md) - MVP 로드맵

---

## ✅ 체크리스트

- [x] Label Studio Docker 환경 구축
- [x] 89개 YOLO 클래스 템플릿 자동 생성
- [x] Windows 원클릭 실행 배치 파일
- [x] SSIM 기반 비디오 샘플링 구현
- [x] CLI 인터페이스 및 옵션 제공
- [x] 상세 문서 작성 (사용 가이드, 문제 해결)
- [x] MVP 로드맵 진행 상황 업데이트
- [x] .gitignore 및 스키마 수정

---

## 📈 커밋 이력

1. **feat: Label Studio 환경 구축 및 SSIM 기반 비디오 샘플링 구현** (`dc88a55`)
   - Label Studio Docker 설정
   - 89개 YOLO 클래스 수집 및 템플릿 생성
   - SSIM 샘플링 알고리즘 구현
   - 문서화

2. **feat: Windows 배치 파일로 Label Studio 원클릭 실행 지원** (`3b3a0d5`)
   - start/stop/open/view-logs 배치 파일
   - README-LABEL-STUDIO.md 작성
   - README.md 업데이트

3. **docs: MVP 로드맵 진행 상황 업데이트** (`30ead5c`)
   - 완료된 작업 체크
   - 진행률 업데이트 (~18%)

---

**다음 단계**: 비디오 녹화 및 프레임 추출 → 라벨링 작업 시작 (Day 17-21)
