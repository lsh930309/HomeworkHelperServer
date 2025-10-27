# VM + Docker 서버 아키텍처 설계

**프로젝트**: HomeworkHelper Phase 1
**작성일**: 2025-10-27
**버전**: v1.1 (Gemini 피드백 반영)

---

## 개요

Phase 1에서는 **로컬 VM 환경**에서 프로덕션과 유사한 서버 아키텍처를 구축합니다. 클라우드 호스팅은 Phase 2에서 진행하며, Phase 1에서는 **비용 0원**으로 완전한 백엔드 시스템을 개발하고 테스트합니다.

### 목표
- VM 기반 개발 환경 구축 (VirtualBox/VMware)
- Docker Compose로 서비스 오케스트레이션
- FastAPI 백엔드 API 서버
- PostgreSQL 데이터베이스
- 로컬 네트워크에서 PC/Android 앱 연동

### Nginx를 사용하는 이유
**"왜 uvicorn이 있는데 nginx를 또 쓰나요?"**

Nginx는 리버스 프록시로서 다음 역할을 합니다:
- **로드 밸런싱**: 여러 FastAPI 인스턴스 운영 시 부하 분산
- **SSL 터미네이션**: Phase 2에서 HTTPS 적용 시 인증서 관리
- **정적 파일 서빙**: uvicorn보다 효율적으로 정적 파일 제공
- **보안**: 외부에 직접 애플리케이션 서버를 노출하지 않음

**개발 단계부터 nginx를 도입하면 Phase 2 클라우드 마이그레이션 시 발생할 수 있는 CORS, SSL, 정적 파일 문제를 미리 경험하고 해결할 수 있습니다.**

### ⚠️ 중요 주의사항

1. **YAML 파일 민감성**: `netplan` 설정과 `docker-compose.yml`은 YAML 형식으로, **띄어쓰기 한 칸**에 매우 민감합니다. 복사/붙여넣기 시 포맷이 깨지지 않도록 주의하세요.

2. **Windows/Linux 줄바꿈 차이**: Git으로 Windows에서 작업한 파일을 Linux VM에서 실행할 때 줄바꿈 문자(CRLF vs LF) 차이로 오작동할 수 있습니다. `.gitattributes`에 `* text=auto eol=lf` 설정이 적용되어 있습니다.

3. **재로그인 필수**: Docker 그룹 추가 후 **반드시 VM에서 로그아웃 후 재로그인** 또는 재부팅해야 합니다.

---

## 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────┐
│                        Host PC (Windows)                     │
│                                                              │
│  ┌─────────────────┐          ┌──────────────────┐          │
│  │ PC 클라이언트   │          │ Android 에뮬레이터│          │
│  │ (Phase 0)       │          │ (테스트용)        │          │
│  └────────┬────────┘          └─────────┬────────┘          │
│           │                              │                   │
│           └──────────┬───────────────────┘                   │
│                      │ HTTP (192.168.x.x:8000)               │
└──────────────────────┼───────────────────────────────────────┘
                       │
                       │ Host-Only Network
                       ▼
┌─────────────────────────────────────────────────────────────┐
│               Virtual Machine (Ubuntu 22.04 LTS)            │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          Docker Compose 스택                         │   │
│  │                                                       │   │
│  │  ┌────────────────┐       ┌──────────────────┐      │   │
│  │  │  nginx         │       │  fastapi-server  │      │   │
│  │  │  (리버스 프록시)│◄──────┤  (Python 3.11)   │      │   │
│  │  │  Port: 80      │       │  Port: 8000      │      │   │
│  │  └────────┬───────┘       └─────────┬────────┘      │   │
│  │           │                          │               │   │
│  │           │                          ▼               │   │
│  │           │                 ┌────────────────┐       │   │
│  │           │                 │  postgres      │       │   │
│  │           │                 │  (PostgreSQL15)│       │   │
│  │           │                 │  Port: 5432    │       │   │
│  │           │                 └────────────────┘       │   │
│  │           │                                          │   │
│  │           └─────► Static Files (선택적)              │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  볼륨 (Docker Volumes)                                       │
│  - postgres-data: PostgreSQL 데이터 영속성                   │
│  - server-logs: FastAPI 로그 파일                           │
└─────────────────────────────────────────────────────────────┘
```

---

## VM 환경 설정

### 1. VM 생성

**권장 스펙**:
- **OS**: Ubuntu 22.04 LTS Server (최소 설치)
- **CPU**: 2 cores (호스트 PC 사양에 따라 조정)
- **RAM**: 4GB (최소 2GB)
- **디스크**: 20GB (동적 할당)
- **네트워크**: Host-Only + NAT (두 개의 어댑터)

**설치 방법**:

#### 옵션 A: VirtualBox (무료, 권장)
```bash
# 1. VirtualBox 설치 (Windows)
# https://www.virtualbox.org/wiki/Downloads

# 2. Ubuntu 22.04 LTS ISO 다운로드
# https://ubuntu.com/download/server

# 3. VM 생성
# - New VM → Ubuntu 64-bit
# - RAM: 4096MB
# - Disk: 20GB VDI (동적 할당)

# 4. 네트워크 설정
# - Adapter 1: NAT (인터넷 연결용)
# - Adapter 2: Host-Only Adapter (호스트 PC 연결용)
```

#### 옵션 B: VMware Workstation Player (무료 개인 사용)
```bash
# 유사한 설정, 네트워크는 NAT + Host-Only로 설정
```

### 2. 네트워크 설정

**목표**: 호스트 PC에서 `http://192.168.56.10:8000`으로 VM 서버 접속

**VirtualBox Host-Only 네트워크**:
```bash
# VirtualBox 설정
File → Host Network Manager → Create
  - IPv4 Address: 192.168.56.1
  - Subnet Mask: 255.255.255.0
  - DHCP Server: 비활성화 (고정 IP 사용)

# VM 네트워크 설정 (Ubuntu)
sudo nano /etc/netplan/00-installer-config.yaml

# 내용:
network:
  version: 2
  ethernets:
    enp0s3:  # NAT (인터넷)
      dhcp4: true
    enp0s8:  # Host-Only
      addresses:
        - 192.168.56.10/24

# 적용
sudo netplan apply

# 확인
ip addr show
ping 8.8.8.8  # 인터넷 연결 확인
```

**호스트 PC에서 접속 테스트**:
```bash
# Windows CMD 또는 PowerShell
ping 192.168.56.10
```

### 3. SSH 설정 (편의성)

```bash
# VM에서 SSH 서버 설치
sudo apt update
sudo apt install openssh-server -y
sudo systemctl enable ssh
sudo systemctl start ssh

# 호스트 PC에서 SSH 접속 (Git Bash, PowerShell, PuTTY 등)
ssh username@192.168.56.10

# (선택) SSH 키 기반 인증 설정
ssh-keygen -t ed25519
ssh-copy-id username@192.168.56.10
```

---

## Docker 환경 구축

### 1. Docker 및 Docker Compose 설치

```bash
# VM (Ubuntu)에서 실행

# 1. 기존 Docker 제거 (있는 경우)
sudo apt remove docker docker-engine docker.io containerd runc

# 2. Docker 공식 저장소 추가
sudo apt update
sudo apt install ca-certificates curl gnupg lsb-release -y

sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 3. Docker 설치
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin -y

# 4. 현재 사용자를 docker 그룹에 추가 (sudo 없이 docker 명령 사용)
sudo usermod -aG docker $USER
newgrp docker  # 또는 재로그인

# 5. 설치 확인
docker --version
docker compose version  # docker-compose-plugin 사용

# 6. 테스트
docker run hello-world
```

### 2. 프로젝트 디렉토리 구조

```bash
# VM에서 프로젝트 클론
cd ~
git clone https://github.com/lsh930309/HomeworkHelperServer.git
cd HomeworkHelperServer

# 디렉토리 구조 (Phase 1 완료 시)
HomeworkHelperServer/
├── server/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI 앱 엔트리포인트
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py      # 인증 API
│   │   │   ├── sessions.py  # 세션 API
│   │   │   └── events.py    # 이벤트 API
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py    # 설정 (환경 변수)
│   │   │   ├── security.py  # JWT 인증
│   │   │   └── database.py  # DB 연결
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── models.py    # SQLAlchemy 모델
│   │   └── schemas/
│   │       ├── __init__.py
│   │       └── schemas.py   # Pydantic 스키마
│   ├── alembic/             # DB 마이그레이션
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── docker-compose.yml
└── docs/
```

---

## Docker Compose 설정

### docker-compose.yml

```yaml
version: '3.8'

services:
  # PostgreSQL 데이터베이스
  postgres:
    image: postgres:15-alpine
    container_name: homework_postgres
    environment:
      POSTGRES_DB: homework_helper_db
      POSTGRES_USER: homework_user
      POSTGRES_PASSWORD: ${DB_PASSWORD:-changeme}  # .env 파일에서 읽기
      POSTGRES_INITDB_ARGS: "--encoding=UTF-8"
    ports:
      - "5432:5432"  # 호스트 PC에서 접근 가능 (선택적)
    volumes:
      - postgres-data:/var/lib/postgresql/data
    networks:
      - homework-network
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U homework_user"]
      interval: 10s
      timeout: 5s
      retries: 5

  # FastAPI 백엔드
  fastapi-server:
    build:
      context: ./server
      dockerfile: Dockerfile
    container_name: homework_fastapi
    environment:
      - DATABASE_URL=postgresql://homework_user:${DB_PASSWORD:-changeme}@postgres:5432/homework_helper_db
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
      - API_HOST=0.0.0.0
      - API_PORT=8000
    ports:
      - "8000:8000"
    volumes:
      - ./server:/app  # 개발 시 코드 hot-reload
      - server-logs:/app/logs
    networks:
      - homework-network
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  # Nginx 리버스 프록시 (선택적, 프로덕션 유사 환경)
  nginx:
    image: nginx:alpine
    container_name: homework_nginx
    ports:
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    networks:
      - homework-network
    depends_on:
      - fastapi-server
    restart: unless-stopped

volumes:
  postgres-data:
    driver: local
  server-logs:
    driver: local

networks:
  homework-network:
    driver: bridge
```

### server/Dockerfile

```dockerfile
# Python 3.11 베이스 이미지
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 패키지 업데이트 및 필수 패키지 설치
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY . .

# 포트 노출
EXPOSE 8000

# 애플리케이션 실행 (docker-compose.yml의 command로 오버라이드됨)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### server/requirements.txt

```txt
# FastAPI 및 서버
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-multipart==0.0.6

# 데이터베이스
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
alembic==1.12.1

# 인증
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-dotenv==1.0.0

# 유틸리티
pydantic==2.5.0
pydantic-settings==2.1.0
```

---

## FastAPI 서버 구조

### server/app/main.py

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import auth, sessions, events

app = FastAPI(
    title="HomeworkHelper API",
    version="1.0.0",
    description="Phase 1: VM 로컬 서버"
)

# CORS 설정 (Android 앱 연동)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["sessions"])
app.include_router(events.router, prefix="/api/v1/events", tags=["events"])

@app.get("/")
def read_root():
    return {"message": "HomeworkHelper API Server", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
```

### server/app/core/config.py

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30일

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://192.168.56.1:8000"]

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## PostgreSQL 스키마 설계

### ER 다이어그램

```
┌─────────────────┐
│     users       │
├─────────────────┤
│ id (PK)         │
│ username        │
│ email           │
│ password_hash   │
│ created_at      │
└────────┬────────┘
         │ 1
         │
         │ N
┌────────▼────────┐
│    sessions     │
├─────────────────┤
│ id (PK)         │
│ user_id (FK)    │
│ process_id      │
│ game_name       │
│ start_ts        │
│ end_ts          │
│ duration        │
│ created_at      │
└────────┬────────┘
         │ 1
         │
         │ N
┌────────▼────────┐
│     events      │
├─────────────────┤
│ id (PK)         │
│ session_id (FK) │
│ event_type      │
│ resource_type   │
│ value           │
│ timestamp       │
│ created_at      │
└─────────────────┘

┌─────────────────┐
│  predictions    │
├─────────────────┤
│ id (PK)         │
│ session_id (FK) │
│ predicted_action│
│ predicted_value │
│ confidence      │
│ created_at      │
└─────────────────┘
```

### SQLAlchemy 모델 (server/app/models/models.py)

```python
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("Session", back_populates="user")

class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    process_id = Column(Integer)
    game_name = Column(String(100))
    start_ts = Column(DateTime, nullable=False)
    end_ts = Column(DateTime)
    duration = Column(Integer)  # 초 단위
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="sessions")
    events = relationship("Event", back_populates="session")
    predictions = relationship("Prediction", back_populates="session")

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    event_type = Column(String(50))  # "resource_change", "action_start", etc.
    resource_type = Column(String(50))  # "stamina", "currency", etc.
    value = Column(Integer)
    timestamp = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="events")

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    predicted_action = Column(String(100))  # "raid", "daily_quest", etc.
    predicted_value = Column(Integer)  # 예상 자원량
    confidence = Column(Float)  # 0.0 ~ 1.0
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="predictions")
```

---

## 실행 및 테스트

### 1. 환경 변수 설정

```bash
# VM에서 실행
cd ~/HomeworkHelperServer/server
cp .env.example .env
nano .env

# .env 파일 내용 (예시)
DATABASE_URL=postgresql://homework_user:mypassword123@postgres:5432/homework_helper_db
JWT_SECRET_KEY=your-super-secret-key-change-this-in-production
DB_PASSWORD=mypassword123
```

### 2. Docker Compose 실행

```bash
# VM에서 실행
cd ~/HomeworkHelperServer

# 백그라운드 실행
docker compose up -d

# 로그 확인
docker compose logs -f

# 개별 서비스 로그
docker compose logs -f fastapi-server
docker compose logs -f postgres

# 서비스 상태 확인
docker compose ps
```

### 3. API 테스트

**호스트 PC에서 브라우저 또는 curl 사용**:

```bash
# 기본 엔드포인트
curl http://192.168.56.10:8000/
# {"message":"HomeworkHelper API Server","version":"1.0.0"}

# Health Check
curl http://192.168.56.10:8000/health
# {"status":"ok"}

# Swagger UI (API 문서)
# 브라우저에서: http://192.168.56.10:8000/docs
```

---

## 다음 단계

1. **FastAPI API 엔드포인트 구현** (`feature/server-auth-api`)
   - POST /api/v1/auth/register
   - POST /api/v1/auth/login
   - POST /api/v1/sessions
   - GET /api/v1/sync/{user_id}

2. **Alembic 마이그레이션 설정**
   - 데이터베이스 스키마 버전 관리

3. **단위 테스트 작성** (pytest)
   - API 엔드포인트 테스트
   - 데이터베이스 CRUD 테스트

4. **Android 앱 연동 테스트**
   - Retrofit으로 VM 서버 API 호출

---

## Gemini 피드백 개선사항 체크리스트

### 즉시 적용 (개발 시작 전)

- [ ] **네트워크 어댑터 이름 확인**
  - `ip addr` 명령어로 실제 어댑터 이름 확인 후 `netplan` 설정 수정
  - `enp0s3`, `enp0s8`은 환경마다 다를 수 있음

- [ ] **보안 강화**
  - [ ] `.env` 파일을 프로젝트 루트에 두고 `.gitignore`에 추가 확인
  - [ ] PostgreSQL 포트 노출 (`ports: "5432:5432"`) 주석 처리 (디버깅 시에만 사용)
  - [ ] 강력한 JWT 시크릿 생성: `openssl rand -hex 32`
  - [ ] `.env` 파일에 실제 값 입력 (예시 값 `changeme` 절대 그대로 사용하지 말 것)

### 개발 시작 후

- [ ] **Docker Compose 설정 분리**
  - [ ] `docker-compose.override.yml` 파일 생성 (개발용 설정)
  - [ ] 개발: `docker compose up -d` (자동으로 override 적용)
  - [ ] 프로덕션 흉내: `docker compose -f docker-compose.yml up -d`

- [ ] **Nginx 설정 파일 작성**
  - [ ] `nginx/nginx.conf` 파일 생성
  - [ ] FastAPI로 프록시하는 기본 설정 추가

- [ ] **FastAPI CRUD 레이어 분리**
  - [ ] `app/crud/` 디렉토리 생성
  - [ ] `crud_user.py`, `crud_session.py` 등 생성
  - [ ] API 라우터는 HTTP 요청/응답만 담당하도록 리팩토링

### 데이터베이스 스키마 개선

- [ ] **타임스탬프 개선**
  ```python
  updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
  ```

- [ ] **User 모델 개선**
  ```python
  is_active = Column(Boolean, default=True)  # Soft delete
  ```

- [ ] **Event 모델 유연성**
  ```python
  value = Column(JSON)  # Integer 대신 JSON 타입
  ```

- [ ] **외래 키 인덱스 추가**
  ```python
  user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
  session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False, index=True)
  ```

### 추가 문서 작성 (선택)

- [ ] Nginx 설정 가이드 (`docs/nginx-setup.md`)
- [ ] CRUD 레이어 설계 가이드 (`docs/crud-layer-design.md`)
- [ ] 보안 체크리스트 (`docs/security-checklist.md`)

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-10-27
**다음 문서**: `fastapi-api-spec.md` (API 상세 스펙)
