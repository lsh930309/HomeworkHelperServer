# Git 브랜치 전략 (Git Workflow)

**프로젝트**: HomeworkHelper
**작성일**: 2025-10-27
**버전**: v1.1 (Gemini 피드백 반영)

---

## 개요

HomeworkHelper 프로젝트는 **PC 클라이언트**, **백엔드 서버**, **Android 앱**으로 구성된 크로스 플랫폼 프로젝트입니다. 이 문서는 효율적인 개발과 배포를 위한 Git 브랜치 전략을 정의합니다.

---

## 브랜치 구조

### 1. 영구 브랜치 (Permanent Branches)

#### `main`
- **목적**: 프로덕션 배포 브랜치
- **보호**: Direct push 금지, PR을 통해서만 merge
- **배포**: main에 merge 시 자동으로 릴리스 생성 (GitHub Actions)
- **태깅**: 각 릴리스마다 시맨틱 버저닝 태그 (`v1.0.0`, `v1.1.0` 등)

#### `develop`
- **목적**: 개발 통합 브랜치
- **특징**: 모든 feature 브랜치는 develop에서 분기하고 develop으로 merge
- **안정성**: 항상 빌드 가능한 상태 유지
- **테스트**: develop에 merge 전 로컬 테스트 필수

---

### 2. 임시 브랜치 (Temporary Branches)

#### Feature 브랜치
**네이밍 규칙**: `feature/{component}-{description}` (작은 기능 단위 권장)

**⭐ 1인 개발 최적화 전략**:
- **작은 단위로 자주 통합**: 큰 feature 브랜치를 오래 유지하면 충돌 위험 증가
- **권장**: 하나의 기능 완성 시마다 즉시 `develop`에 merge (Squash and Merge)
- **예**: `feature/phase1-fastapi-api` (큰 브랜치) 대신
  - `feature/server-auth-api` (인증 API만)
  - `feature/server-session-upload` (세션 업로드만)
  - `feature/server-jwt-middleware` (JWT 미들웨어만)

**Phase 1 권장 예시** (작은 단위):
- `feature/server-initial-setup` - FastAPI 프로젝트 초기 설정
- `feature/server-auth-api` - 인증 API (회원가입/로그인)
- `feature/server-session-upload` - 세션 업로드 API
- `feature/db-schema-setup` - PostgreSQL 스키마 초기 설정
- `feature/android-project-setup` - Android 프로젝트 생성
- `feature/android-usage-stats` - UsageStatsManager 구현
- `feature/label-studio-docker` - Label Studio Docker 설정

**Phase 1 큰 단위 예시** (비추천, 참고용):
- `feature/phase1-vm-server` - VM + Docker 서버 전체
- `feature/phase1-fastapi-api` - FastAPI 백엔드 전체
- `feature/phase1-android-mvp` - Android 앱 전체

**Phase 2 예시**:
- `feature/cloud-vercel-deploy` - Vercel 배포 설정
- `feature/yolo-dataset-prep` - YOLO 데이터셋 준비
- `feature/yolo-model-training` - YOLO 모델 학습
- `feature/ai-action-classifier` - AI 행동 분류 모델

**워크플로우** (Rebase 활용):
```bash
# develop에서 feature 브랜치 생성
git checkout develop
git pull origin develop
git checkout -b feature/server-auth-api

# 작업 후 커밋 (여러 번 커밋 가능)
git add .
git commit -m "feat(server): 회원가입 API 추가"
git commit -m "feat(server): 로그인 API 추가"

# PR 전에 develop 최신 변경사항 반영 (Rebase 권장)
git fetch origin
git rebase origin/develop
# 충돌 발생 시 해결 후 git rebase --continue

# PR 생성 또는 직접 merge
git push origin feature/server-auth-api
# GitHub에서 PR 생성 → Squash and Merge

# 또는 로컬에서 직접 merge (1인 개발 시)
git checkout develop
git merge --squash feature/server-auth-api
git commit -m "feat(server): 인증 API 추가 (#1)"
git push origin develop

# feature 브랜치 삭제
git branch -d feature/server-auth-api
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

## Phase별 브랜치 전략

### Phase 0 (완료)
- `main`: PC 클라이언트 Phase 0 기능 완성
- Phase 0은 단일 저장소에서 개발 완료

### Phase 1 (현재)
**목표**: VM 서버 + Android 앱 + Label Studio

**⭐ 작은 단위 릴리스 전략** (권장):
Phase 전체 완료를 기다리지 않고, 기능이 완성될 때마다 `main`에 릴리스합니다.

**릴리스 계획**:
1. **v1.0.0** - VM + Docker + FastAPI 기본 API 완성
   - `feature/server-initial-setup`
   - `feature/docker-compose-setup`
   - `feature/server-auth-api`
   - `feature/db-schema-setup`

2. **v1.1.0** - Android 앱 기본 기능 추가
   - `feature/android-project-setup`
   - `feature/android-usage-stats`
   - `feature/android-server-sync`

3. **v1.2.0** - Label Studio 데이터 수집 환경 완성
   - `feature/label-studio-docker`
   - `feature/label-studio-templates`

**브랜치 계획** (작은 단위):

```mermaid
graph TD
    develop[develop 브랜치]

    develop --> f1[feature/server-initial-setup]
    develop --> f2[feature/docker-compose-setup]
    develop --> f3[feature/server-auth-api]
    develop --> f4[feature/db-schema-setup]
    develop --> f5[feature/android-project-setup]
    develop --> f6[feature/android-usage-stats]
    develop --> f7[feature/label-studio-docker]

    f1 --> v1[v1.0.0 릴리스]
    f2 --> v1
    f3 --> v1
    f4 --> v1
    f5 --> v11[v1.1.0 릴리스]
    f6 --> v11
    f7 --> v12[v1.2.0 릴리스]

    style develop fill:#4a90e2,stroke:#333,stroke-width:2px
    style v1 fill:#28a745,stroke:#333,stroke-width:2px
    style v11 fill:#28a745,stroke:#333,stroke-width:2px
    style v12 fill:#28a745,stroke:#333,stroke-width:2px
```

**통합 절차**:
1. 각 feature 브랜치는 독립적으로 `develop`에 Squash and Merge
2. `develop`에 릴리스 준비 완료 시 `main`으로 Merge Commit
3. `main`에 merge 후 즉시 시맨틱 버전 태그 생성 (v1.0.0, v1.1.0...)
4. 작은 릴리스 주기로 안정성 확보 (빅뱅 머지 방지)

### Phase 2 이후
- Phase 2 시작 시 `develop` 브랜치에서 새로운 feature 브랜치 생성
- 클라우드 마이그레이션: `feature/phase2-cloud-migration`
- YOLO 학습: `feature/phase2-yolo-training`

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

### 즉시 실행 (Phase 1 시작 전)
- [ ] **Git LFS 설정**
  - `git lfs install`
  - `.gitattributes` 파일 생성 (AI 모델, 폰트 추적)
  - 커밋 및 push

- [ ] **`.gitignore` 강화**
  - `.env`, `.env.local`, `.env.*.local` 추가
  - 빌드 결과물 (`dist/`, `build/`, `*.apk`, `*.exe`) 추가
  - Android 관련 (`*.iml`, `.gradle/`, `local.properties`) 추가

- [ ] **환경 변수 관리 체계 구축**
  - `server/.env.example` 파일 생성
  - `.gitignore`에 `.env` 추가

- [ ] **`develop` 브랜치 생성**
  ```bash
  git checkout -b develop
  git push -u origin develop
  ```

- [ ] **Pre-commit 훅 설정 (권장)**
  - `pip install pre-commit`
  - `.pre-commit-config.yaml` 생성
  - `pre-commit install`

### Phase 1 개발 시작
- [ ] 첫 번째 feature 브랜치 생성
  - **권장**: `feature/server-initial-setup` (작은 단위)
  - **비추천**: `feature/phase1-vm-server` (큰 단위)

- [ ] 커밋 메시지 템플릿 작성 (선택)
  - `.gitmessage` 파일 생성
  - `git config commit.template .gitmessage`

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-10-27
