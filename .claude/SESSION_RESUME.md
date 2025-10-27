# 🔄 Claude Code 세션 재개 가이드

**작성일**: 2025-10-27
**상태**: Docker Desktop 설치 완료, PC 재시작 대기 중
**다음 작업**: Docker Compose로 FastAPI 서버 실행 테스트

---

## 📍 현재 진행 상황

### ✅ 완료된 작업

#### 1. Phase 1 서버 초기 설정 완료
- **브랜치**: `feature/server-initial-setup` → `develop` merge 완료
- **커밋**: `b014a68` - FastAPI 서버 초기 설정 (Python 3.13 호환)
- **상태**: origin/develop에 push 완료

#### 2. 구현된 내용
```
server/
├── app/
│   ├── main.py              # FastAPI 엔트리포인트
│   ├── core/
│   │   ├── config.py        # pydantic-settings 설정
│   │   └── database.py      # SQLAlchemy 연결
│   ├── api/                 # API 라우터 (향후 추가)
│   ├── models/              # SQLAlchemy 모델
│   └── schemas/             # Pydantic 스키마
├── requirements.txt         # Python 3.13 호환
├── requirements-docker.txt  # PostgreSQL 드라이버
├── Dockerfile
└── .env.example
```

#### 3. 기술 스택
- FastAPI 0.115+
- Pydantic V2 (2.11+)
- SQLAlchemy 2.0.35+
- Python 3.13 완전 호환
- Docker Compose (PostgreSQL + FastAPI)

#### 4. 검증 완료
- ✅ Gemini CLI 코드 검토 통과
- ✅ Python 3.13 호환성 확인
- ✅ 아키텍처 설계 검증

---

## 🎯 다음 작업 (PC 재시작 후)

### Step 1: Docker Desktop 실행 확인
```bash
# 1. Docker Desktop 수동 실행 (시작 메뉴에서)
# 2. Docker 상태 확인
docker --version
docker compose version
docker info
```

### Step 2: 환경 변수 설정
```bash
# server/.env 파일 생성
cd server
cp .env.example .env

# .env 파일 편집 (필수)
# DATABASE_URL=postgresql://homework_user:changeme@postgres:5432/homework_helper_db
# JWT_SECRET_KEY=<openssl rand -hex 32로 생성한 키>
# DB_PASSWORD=changeme
```

**중요**: JWT_SECRET_KEY는 반드시 강력한 키로 교체하세요!
```bash
# PowerShell에서 실행
python -c "import secrets; print(secrets.token_hex(32))"
```

### Step 3: Docker Compose 실행
```bash
# 프로젝트 루트로 이동
cd C:\vscode\project\HomeworkHelperServer

# Docker Compose 실행
docker compose up -d

# 또는 로그 보면서 실행 (권장)
docker compose up
```

### Step 4: 컨테이너 상태 확인
```bash
# 컨테이너 목록 확인
docker compose ps

# 로그 확인
docker compose logs -f

# 개별 서비스 로그
docker compose logs -f fastapi-server
docker compose logs -f postgres
```

**예상 결과**:
```
NAME                IMAGE               STATUS
homework_postgres   postgres:15-alpine  Up (healthy)
homework_fastapi    homework_fastapi    Up
```

### Step 5: API 테스트
```bash
# 1. Health Check
curl http://localhost:8000/health
# 예상 응답: {"status":"ok","version":"1.0.0"}

# 2. 루트 엔드포인트
curl http://localhost:8000/
# 예상 응답: {"message":"HomeworkHelper API","version":"1.0.0","docs":"/docs","status":"running"}

# 3. Swagger UI (브라우저)
# http://localhost:8000/docs

# 4. ReDoc (브라우저)
# http://localhost:8000/redoc
```

### Step 6: PostgreSQL 연결 확인
```bash
# 컨테이너 내부로 접속
docker compose exec postgres psql -U homework_user -d homework_helper_db

# SQL 명령어 테스트
\dt  # 테이블 목록 (아직 비어있음)
\q   # 종료
```

---

## 🐛 문제 해결 가이드

### 문제 1: Docker Compose 실행 오류
```bash
# 에러 로그 확인
docker compose logs

# 컨테이너 재시작
docker compose restart

# 완전 재시작 (볼륨 포함)
docker compose down -v
docker compose up -d
```

### 문제 2: PostgreSQL 연결 실패
- `.env` 파일의 `DATABASE_URL` 확인
- `DB_PASSWORD`가 일치하는지 확인
- `postgres` 컨테이너가 healthy 상태인지 확인

### 문제 3: FastAPI 서버 시작 실패
```bash
# 컨테이너 내부 로그 확인
docker compose logs fastapi-server

# Python 의존성 문제 시 재빌드
docker compose build --no-cache
docker compose up -d
```

### 문제 4: 포트 충돌
```bash
# 8000 포트 사용 중인 프로세스 확인 (PowerShell)
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess

# docker-compose.yml에서 포트 변경
# ports:
#   - "8001:8000"  # 8001로 변경
```

---

## 📝 다음 Feature 작업 계획

### 우선순위 1: 인증 API 구현
```bash
git checkout -b feature/server-auth-api

# 작업 내용:
# - app/api/auth.py 생성
# - POST /api/v1/auth/register
# - POST /api/v1/auth/login
# - JWT 토큰 발급 및 검증
```

### 우선순위 2: 데이터베이스 스키마 설계
```bash
git checkout -b feature/db-schema-setup

# 작업 내용:
# - app/models/models.py 작성 (User, Session, Event, Prediction)
# - Alembic 마이그레이션 초기화
# - 테이블 생성 스크립트
```

### 우선순위 3: Android 프로젝트 생성
```bash
git checkout -b feature/android-project-setup

# 작업 내용:
# - Android Studio 프로젝트 생성
# - Kotlin + Jetpack Compose 설정
# - 기본 디렉토리 구조 생성
```

---

## 🔑 중요 명령어 요약

```bash
# Git 상태
git status
git log --oneline -5

# Docker Compose
docker compose up -d          # 백그라운드 실행
docker compose down           # 중지
docker compose ps             # 상태 확인
docker compose logs -f        # 로그 모니터링
docker compose restart        # 재시작
docker compose build          # 재빌드

# API 테스트
curl http://localhost:8000/health
curl http://localhost:8000/

# 브라우저 테스트
# http://localhost:8000/docs
```

---

## 📊 현재 Git 상태

```
브랜치: develop
최근 커밋: f5c20d6 - Merge feature/server-initial-setup into develop
리모트: origin/develop (up to date)
상태: clean (커밋할 변경 사항 없음)
```

---

## 💡 Claude Code 재시작 시

**이 파일을 Claude에게 보여주고 다음과 같이 요청하세요**:

```
"SESSION_RESUME.md 파일을 읽고, PC 재시작 후 Docker Compose로 서버 테스트를 이어서 진행해줘."
```

또는

```
"Docker Desktop 실행 후 FastAPI 서버를 docker compose로 실행하고 테스트해줘."
```

---

## 🎯 최종 목표

Phase 1.1 완료:
- ✅ FastAPI 서버 초기 설정
- 🔄 Docker Compose로 서버 실행 및 테스트 (현재 작업)
- ⏳ 인증 API 구현
- ⏳ 데이터베이스 스키마 설계

**예상 소요 시간**: PC 재시작 후 30분 ~ 1시간

---

**작성자**: Claude Code
**버전**: v1.0
**다음 업데이트**: Docker 테스트 완료 후
