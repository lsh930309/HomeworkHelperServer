# Git 브랜치 전략 (Git Workflow)

**프로젝트**: HomeworkHelper
**작성일**: 2025-10-27
**최종 수정**: 2025-11-14
**버전**: v2.0 (MVP 전략 반영)

---

## 개요

HomeworkHelper 프로젝트는 **게임 UI 탐지 및 자동화 시스템**을 위한 MVP(Minimum Viable Product) 개발 프로젝트입니다.

**핵심 개발 전략**:
- **로컬 우선 개발**: 프론트엔드/백엔드 로직을 처음부터 분리하여 개발
- **빠른 프로토타입**: main 브랜치에서 핵심 기능을 빠르게 구현
- **서버 배포 최후반**: 클라우드/VM 서버 배포는 MVP 완성 후 진행

이 문서는 1인 개발 MVP에 최적화된 단순하고 효율적인 Git 워크플로우를 정의합니다.

---

## 브랜치 구조

### 1. 영구 브랜치 (Permanent Branches)

#### `main` - MVP 개발 브랜치 ⭐
- **목적**: MVP 프로토타입 개발의 메인 브랜치
- **특징**:
  - 빠른 기능 구현과 반복을 위한 유연한 워크플로우
  - 1인 개발이므로 직접 push 가능 (작은 변경사항)
  - 큰 기능은 feature 브랜치 사용 권장
- **안정성**: 동작하는 코드 유지 (빌드 가능한 상태)
- **태깅**: 주요 마일스톤 완료 시 태그 (`mvp-v0.1`, `mvp-v0.2` 등)

#### `develop` - 현재 보류 ⏸️
- **상태**: MVP 개발 중에는 사용하지 않음
- **목적**: 향후 서버 배포 단계에서 활용 예정
- **계획**: MVP 완성 후 main → develop 분리 고려

---

### 2. 임시 브랜치 (Temporary Branches)

#### Feature 브랜치
**네이밍 규칙**: `feature/{component}-{description}` (작은 기능 단위 권장)

**⭐ MVP 개발 최적화 전략**:
- **작은 단위로 빠르게**: 기능을 작은 단위로 나누어 빠르게 구현하고 main에 통합
- **권장**: 1-2일 내에 완성 가능한 크기의 feature 브랜치
- **간단한 변경**: main에 직접 커밋 가능 (문서 수정, 버그 픽스 등)

**현재 MVP 브랜치 예시**:
- `feature/dataset-schema` - 게임별 데이터셋 스키마 정의
- `feature/label-studio-setup` - Label Studio 환경 구축
- `feature/video-sampling` - SSIM 기반 스마트 비디오 샘플링
- `feature/yolo-training-pipeline` - YOLO 학습 파이프라인 구축
- `feature/ocr-integration` - OCR 엔진 통합 (Tesseract/EasyOCR)
- `feature/ui-detection-test` - UI 탐지 시스템 테스트

**워크플로우** (단순화):
```bash
# main에서 feature 브랜치 생성
git checkout main
git pull origin main
git checkout -b feature/dataset-schema

# 작업 후 커밋
git add .
git commit -m "feat: 게임별 데이터셋 스키마 정의"

# main에 직접 merge (1인 개발)
git checkout main
git merge feature/dataset-schema
git push origin main

# feature 브랜치 삭제
git branch -d feature/dataset-schema
```

**더 간단한 워크플로우** (작은 변경):
```bash
# main에서 직접 작업
git checkout main
git pull origin main

# 작업 후 커밋 및 푸시
git add .
git commit -m "docs: update milestone roadmap"
git push origin main
```

#### Bugfix 브랜치
**네이밍 규칙**: `bugfix/{issue-number}-{description}`

**예시**:
- `bugfix/123-fix-database-connection` - DB 연결 오류 수정
- `bugfix/456-android-crash` - Android 앱 크래시 수정

#### Hotfix 브랜치
**네이밍 규칙**: `hotfix/{version}-{description}`

**용도**: 프로덕션 긴급 수정
**워크플로우**:
```bash
# main에서 hotfix 브랜치 생성
git checkout main
git checkout -b hotfix/1.0.1-critical-bug

# 수정 후 main과 develop 모두에 merge
git checkout main
git merge hotfix/1.0.1-critical-bug
git tag v1.0.1
git push origin main --tags

git checkout develop
git merge hotfix/1.0.1-critical-bug
git push origin develop
```

---

## 커밋 메시지 규칙

### Conventional Commits 사용

**형식**:
```
<type>(<scope>): <subject>

<body>

<footer>
```

**타입 (Type)**:
- `feat`: 새로운 기능 추가
- `fix`: 버그 수정
- `docs`: 문서 변경
- `style`: 코드 포맷팅 (기능 변경 없음)
- `refactor`: 리팩토링
- `test`: 테스트 추가/수정
- `chore`: 빌드, 설정 파일 변경

**스코프 (Scope)** (선택):
- `server`: 백엔드 서버
- `android`: Android 앱
- `pc`: PC 클라이언트
- `db`: 데이터베이스
- `docker`: Docker 관련

**예시**:
```
feat(server): FastAPI 세션 업로드 API 추가

POST /api/v1/sessions 엔드포인트 구현
- 세션 데이터 검증
- PostgreSQL 저장
- JWT 인증 적용

Closes #123
```

```
fix(android): UsageStatsManager 권한 체크 로직 수정

Android 8.0 이하에서 권한 체크 오류 수정
```

---

## MVP 개발 전략

### 현재 (MVP Phase)
**목표**: 게임 UI 탐지 엔진 프로토타입 (YOLO + OCR)

**핵심 마일스톤**:
1. **게임별 데이터셋 정의** (재화, 콘텐츠, 숙제 목록)
   - `feature/dataset-schema`
   - `feature/game-resource-definitions`

2. **Label Studio 데이터셋 구축 시스템**
   - `feature/label-studio-setup`
   - `feature/video-sampling` (SSIM 기반)
   - `feature/labeling-pipeline`

3. **YOLO 모델 학습 및 테스트**
   - `feature/yolo-training-pipeline`
   - `feature/model-evaluation`
   - `feature/ocr-integration`

**브랜치 계획** (main 중심):
```
main
├── feature/dataset-schema
├── feature/label-studio-setup
├── feature/video-sampling
├── feature/yolo-training-pipeline
├── feature/ocr-integration
└── feature/ui-detection-test
```

**릴리스 전략**:
- 주요 마일스톤 완료 시 태그 생성
- `mvp-v0.1`: 데이터셋 스키마 완성
- `mvp-v0.2`: Label Studio 환경 구축
- `mvp-v0.3`: YOLO 첫 학습 완료
- `mvp-v1.0`: UI 탐지 시스템 프로토타입 완성

### 향후 (서버 배포 Phase)
- **보류**: MVP 완성 후 진행
- **계획**:
  - `develop` 브랜치 재활성화
  - 서버 배포 관련 feature 브랜치 생성
  - 클라우드 마이그레이션 작업

---

## 저장소 구조 (향후 고려)

### 옵션 A: 모노레포 (Monorepo) - 현재 방식 ⭐
**장점**:
- 단일 저장소에서 모든 코드 관리
- PC/서버/Android 코드 동기화 용이
- 공통 문서, 이슈 관리 편리

**단점 및 해결책**:
- ~~저장소 크기 증가 (특히 Android APK, YOLO 모델 파일)~~ → **Git LFS 도입으로 해결** (아래 참조)
- 브랜치 복잡도 증가 → 작은 단위 브랜치 전략으로 완화

**⚠️ 필수: Git LFS 즉시 도입**
대용량 파일은 Git LFS(Large File Storage)로 관리하여 저장소 크기 문제를 해결합니다.

**추적 대상 파일**:
- AI 모델: `*.pt`, `*.onnx`, `*.pkl`, `*.h5`
- 폰트: `*.otf`, `*.ttf`
- 이미지/아이콘: `*.png`, `*.jpg` (큰 파일만)
- 빌드 결과물: `*.apk`, `*.exe` (릴리스용, GitHub Releases 권장)

**설정 방법**:
```bash
# Git LFS 설치 (Windows: Git 설치 시 포함)
git lfs install

# .gitattributes 파일 생성 및 추적 설정
git lfs track "*.pt"
git lfs track "*.onnx"
git lfs track "*.pkl"
git lfs track "*.h5"
git lfs track "*.otf"
git lfs track "*.ttf"

# .gitattributes 커밋
git add .gitattributes
git commit -m "chore: Git LFS 설정 추가"
```

**구조**:
```
HomeworkHelperServer/
├── pc/                 # PC 클라이언트 (Python)
├── server/             # FastAPI 백엔드
├── android/            # Android 앱 (Kotlin)
├── models/             # AI 모델 (YOLO, XGBoost)
├── docs/               # 문서
└── docker-compose.yml  # Docker 설정
```

### 옵션 B: 멀티레포 (Multi-repo)
**구조**:
- `HomeworkHelper-PC` (PC 클라이언트)
- `HomeworkHelper-Server` (백엔드)
- `HomeworkHelper-Android` (Android 앱)

**장점**: 각 컴포넌트 독립 관리
**단점**: 동기화 어려움, 이슈 관리 분산

**결정**: Phase 1에서는 모노레포 유지, Phase 2 클라우드 마이그레이션 시 재검토

---

## PR (Pull Request) 규칙

### PR 생성 시
1. **제목**: `[Phase X] {type}: {간단한 설명}`
   - 예: `[Phase 1] feat: FastAPI 세션 업로드 API 추가`
2. **본문**:
   - 변경 사항 요약 (Summary)
   - 테스트 방법 (Test Plan)
   - 스크린샷 (UI 변경 시)
3. **리뷰어**: 셀프 리뷰 (1인 개발)

### Merge 규칙
- **Squash and Merge**: feature 브랜치 → develop (히스토리 정리)
- **Merge Commit**: develop → main (Phase 완료 시)

---

## 태깅 규칙 (Semantic Versioning)

**형식**: `v{MAJOR}.{MINOR}.{PATCH}`

- **MAJOR**: 호환성이 깨지는 변경 (Phase 전환)
- **MINOR**: 새로운 기능 추가 (하위 호환)
- **PATCH**: 버그 수정

**예시**:
- `v0.1.0`: Phase 0 첫 릴리스
- `v1.0.0`: Phase 1 완료 (VM 서버 + Android MVP)
- `v1.1.0`: Phase 1 마이너 업데이트 (Label Studio 완성)
- `v2.0.0`: Phase 2 완료 (클라우드 마이그레이션 + YOLO)

---

## 환경 변수 관리 ⭐

**⚠️ 필수: `.env` 파일 관리**
DB 접속 정보, API 키 등 민감한 정보는 `.env` 파일로 관리하고, 절대 Git에 커밋하지 않습니다.

**설정 방법**:
1. **`.env.example` 파일 생성** (서버용):
   ```env
   # Database
   DATABASE_URL=postgresql://user:password@localhost:5432/homework_helper

   # JWT Secret
   JWT_SECRET_KEY=your-secret-key-here
   JWT_ALGORITHM=HS256

   # API Settings
   API_HOST=0.0.0.0
   API_PORT=8000
   ```

2. **`.gitignore`에 추가**:
   ```
   # Environment variables
   .env
   .env.local
   .env.*.local
   ```

3. **개발 시**:
   ```bash
   # .env.example을 복사하여 .env 생성
   cp server/.env.example server/.env
   # .env 파일 편집하여 실제 값 입력
   ```

---

## Git Hooks (즉시 도입 권장) ⭐

**⚠️ 권장: `pre-commit` 훅 조기 도입**
코드 품질을 일정하게 유지하기 위해 커밋 전 자동 검사를 설정합니다.

### pre-commit (로컬)
**설치 방법**:
```bash
# Python pre-commit 패키지 설치
pip install pre-commit

# .pre-commit-config.yaml 생성 (프로젝트 루트)
cat > .pre-commit-config.yaml << EOF
repos:
  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black
        language_version: python3.11

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: ['--max-line-length=88']

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=1000']
EOF

# 훅 설치
pre-commit install
```

**동작**:
- `git commit` 실행 시 자동으로 black(포맷터), flake8(린터) 실행
- 검사 실패 시 커밋 차단

### pre-push (선택)
- 단위 테스트 실행
- 빌드 성공 확인
- Phase 2 이후 도입 검토

---

## GitHub Actions CI/CD (Phase 2에서 구현)

### develop 브랜치
- 자동 테스트 실행
- Docker 이미지 빌드 (테스트용)

### main 브랜치
- 자동 릴리스 생성
- GitHub Releases에 빌드 파일 업로드 (PC: EXE, Android: APK)
- 클라우드 자동 배포 (Phase 2부터)

---

## 다음 액션 아이템 (우선순위 순)

### 즉시 실행 (MVP 시작 전)
- [x] **Git LFS 설정** (이미 완료된 경우 체크)
  - `git lfs install`
  - `.gitattributes` 파일 확인 (AI 모델, 폰트 추적)

- [ ] **`.gitignore` 강화**
  - YOLO 학습 임시 파일 (`runs/`, `weights/`, `*.cache`)
  - Label Studio 데이터 (`label-studio-data/`)
  - 비디오 샘플링 출력 (`samples/`, `frames/`)
  - Python 캐시 (`__pycache__/`, `*.pyc`)

- [ ] **Pre-commit 훅 설정 (권장)**
  - `pip install pre-commit`
  - `.pre-commit-config.yaml` 생성
  - `pre-commit install`

### MVP 개발 시작
- [ ] **main 브랜치 확인**
  ```bash
  git checkout main
  git pull origin main
  ```

- [ ] **첫 번째 feature 브랜치 생성**
  ```bash
  git checkout -b feature/dataset-schema
  ```

- [ ] **커밋 메시지 템플릿 작성** (선택)
  - `.gitmessage` 파일 생성
  - `git config commit.template .gitmessage`

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-10-27
