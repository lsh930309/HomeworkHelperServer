# 🏗️ HomeworkHelper 아키텍처 가이드

> **작성일**: 2025-10-29
> **버전**: 1.0.0
> **목적**: 프로젝트의 기술 부채 해소 및 유지보수성 향상을 위한 아키텍처 문서

---

## 📑 목차

1. [프로젝트 개요](#-프로젝트-개요)
2. [전체 아키텍처](#-전체-아키텍처)
3. [클라이언트 아키텍처](#-클라이언트-아키텍처-데스크톱-앱)
4. [서버 아키텍처](#-서버-아키텍처-dockervm)
5. [데이터 모델](#-데이터-모델)
6. [핵심 컴포넌트 상세](#-핵심-컴포넌트-상세)
7. [데이터 흐름](#-데이터-흐름)
8. [기술 스택](#-기술-스택)
9. [설계 패턴 및 원칙](#-설계-패턴-및-원칙)
10. [보안 및 안정성](#-보안-및-안정성)
11. [확장 계획](#-확장-계획)

---

## 🎯 프로젝트 개요

### 핵심 기능
- **프로세스 모니터링**: 게임/프로그램 실행 상태 실시간 추적
- **세션 트래킹**: 실행 시작/종료 타임스탬프 자동 기록
- **스마트 알림**: 리셋 시간, 필수 플레이 타임, 수면 보정 알림
- **웹 바로가기**: 일일 방문 사이트 관리
- **데이터 분석**: RESTful API를 통한 플레이 패턴 분석

### 주요 사용자
- 게임 일일 퀘스트를 관리하려는 게이머
- 여러 게임의 플레이 시간을 추적하려는 사용자
- 루틴 웹사이트를 자동으로 관리하려는 사용자

---

## 🏛️ 전체 아키텍처

### 시스템 구성도

```mermaid
graph LR
    subgraph System["HomeworkHelper System"]
        subgraph Desktop["데스크톱 클라이언트 (로컬)<br/>Windows 전용"]
            GUI["PyQt6 GUI"]
            EmbeddedAPI["내장 FastAPI<br/>(독립 프로세스)"]
            SQLite["SQLite DB<br/>(WAL 모드)"]
            Monitor["Process Monitor<br/>(psutil)"]
            Scheduler["Scheduler &<br/>Notifier"]
            Tray["System Tray<br/>Integration"]
        end

        subgraph RemoteServer["원격 서버 (Docker/VM)<br/>Multi-Platform"]
            FastAPI["FastAPI Server"]
            PostgreSQL["PostgreSQL DB"]
            JWT["JWT 인증"]
            CORS["CORS 설정"]
            AndroidSync["Android<br/>연동 준비"]
        end
    end

    Desktop -.->|Phase 2| RemoteServer
```

### 아키텍처 타입
- **로컬 앱**: **Monolithic + Microkernel** 하이브리드
  - GUI, 내장 API 서버, 프로세스 모니터가 하나의 애플리케이션에 통합
  - API 서버는 독립 프로세스로 실행 (multiprocessing)

- **원격 서버**: **RESTful API Server**
  - Phase 2: VM 로컬 서버
  - Phase 3: 클라우드 확장 계획

---

## 💻 클라이언트 아키텍처 (데스크톱 앱)

### 레이어 구조

```mermaid
graph TB
    subgraph PresentationLayer["Presentation Layer"]
        MainWindow["MainWindow<br/>(PyQt6)"]
        Dialogs["Dialogs<br/>(PyQt6)"]
        TrayManager["TrayManager<br/>(PyQt6)"]
    end

    subgraph BusinessLogicLayer["Business Logic Layer"]
        ProcessMonitor["Process<br/>Monitor"]
        Scheduler["Scheduler"]
        Notifier["Notifier"]
        Utils["Utils"]
    end

    subgraph APILayer["API Layer (독립 프로세스)"]
        subgraph FastAPIServer["FastAPI Server (main.py)"]
            Routes["Routes"]
            CRUD["CRUD"]
            Schemas["Schemas"]
        end
    end

    subgraph DataLayer["Data Layer"]
        subgraph SQLiteDB["SQLite Database (WAL Mode)"]
            ProcessTable["Process<br/>Table"]
            SessionTable["Session<br/>Table"]
            ShortcutTable["Shortcut<br/>Table"]
            SettingsTable["Settings<br/>Table"]
        end
    end

    PresentationLayer --> BusinessLogicLayer
    BusinessLogicLayer --> APILayer
    APILayer --> DataLayer
```

### 핵심 파일 구조

```
HomeworkHelperServer/
├── 📱 GUI Layer
│   ├── homework_helper.pyw      # 진입점 (multiprocessing 지원)
│   ├── main_window.py            # 메인 윈도우
│   ├── dialogs.py                # 프로세스/웹 추가 다이얼로그
│   ├── tray_manager.py           # 시스템 트레이 관리
│   └── gui_notification_handler.py  # Windows Toast 알림
│
├── 🔍 Business Logic Layer
│   ├── process_monitor.py        # psutil 기반 프로세스 감지
│   ├── scheduler.py              # 알림 스케줄링 로직
│   ├── notifier.py               # 알림 비즈니스 로직
│   ├── data_models.py            # 도메인 모델 (ManagedProcess 등)
│   ├── instance_manager.py       # 단일 인스턴스 관리
│   └── utils.py / windows_utils.py / admin_utils.py
│
├── 🌐 API Layer (독립 프로세스)
│   ├── main.py                   # FastAPI 서버 (내장, run_server_main)
│   ├── crud.py                   # DB CRUD 로직 + 재시도
│   ├── schemas.py                # Pydantic 스키마
│   └── api_client.py             # GUI → API 통신 클라이언트
│
├── 💾 Data Layer
│   ├── database.py               # SQLAlchemy 엔진 + WAL 설정
│   ├── models.py                 # SQLAlchemy 모델
│   └── [%APPDATA%/HomeworkHelper/homework_helper_data/]
│       └── app_data.db           # SQLite 파일
│
└── 🔧 Build & Deploy
    ├── build.py                  # PyInstaller 빌드 스크립트
    ├── homework_helper.spec      # PyInstaller 설정
    ├── installer.iss             # Inno Setup 설치 관리자
    └── requirements.txt
```

### 프로세스 관리

#### 1. GUI 프로세스
- **역할**: 사용자 인터페이스 제공
- **라이프사이클**: 사용자가 종료할 때까지 실행
- **특징**:
  - 시스템 트레이 상주 가능
  - 관리자 권한 재시작 지원
  - 단일 인스턴스 보장 (Windows Mutex)

#### 2. API 서버 프로세스 (독립)
- **역할**: RESTful API 제공, DB 액세스
- **라이프사이클**: GUI 시작 시 자동 시작, 독립 실행
- **특징**:
  - `multiprocessing.Process` 사용
  - `daemon=True`: GUI 종료 시 자동 종료
  - Windows Named Mutex로 중복 실행 방지
  - Graceful Shutdown 지원 (WAL checkpoint)
  - PID 파일 + Mutex 이중 보호

```python
# homework_helper.pyw:192-196
api_server_process = multiprocessing.Process(
    target=run_server_main,
    daemon=True  # 부모 종료 시 자동 종료
)
api_server_process.start()
```

---

## ☁️ 서버 아키텍처 (Docker/VM)

### 컨테이너 구성

```mermaid
graph LR
    subgraph DockerCompose["Docker Compose Stack"]
        FastAPIServer["FastAPI Server<br/>(Port 8000)<br/><br/>- JWT 인증<br/>- CORS 설정<br/>- API v1"]
        PostgreSQL["PostgreSQL<br/>(Port 5432)<br/><br/>- 볼륨 마운트<br/>- Health Check<br/>- 자동 재시작"]
        Nginx["Nginx<br/>(Phase 2)<br/><br/>- 리버스 프록시<br/>- SSL/TLS"]

        Network["homework-network<br/>(bridge)"]
    end

    FastAPIServer -->|DB 연결| PostgreSQL
    Nginx -.->|Phase 2| FastAPIServer

    FastAPIServer ---|네트워크| Network
    PostgreSQL ---|네트워크| Network
    Nginx ---|네트워크| Network
```

### 서버 디렉토리 구조

```
server/
├── Dockerfile                    # FastAPI 컨테이너 이미지
├── requirements.txt              # Python 3.13 호환 의존성
├── requirements-docker.txt       # Docker 전용 (PostgreSQL)
│
├── app/
│   ├── __init__.py
│   ├── main.py                   # FastAPI 앱 진입점
│   │
│   ├── core/
│   │   ├── config.py             # Pydantic Settings
│   │   └── database.py           # SQLAlchemy 엔진 (PostgreSQL)
│   │
│   ├── api/                      # API 엔드포인트 (향후 추가)
│   │   └── __init__.py
│   │
│   ├── models/                   # SQLAlchemy 모델 (향후)
│   │   └── __init__.py
│   │
│   └── schemas/                  # Pydantic 스키마 (향후)
│       └── __init__.py
│
└── alembic/                      # DB 마이그레이션 (향후)
```

### 환경 설정

#### docker-compose.yml
```yaml
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: homework_helper_db
      POSTGRES_USER: homework_user
      POSTGRES_PASSWORD: ${DB_PASSWORD:-changeme}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U homework_user"]
      interval: 10s

  fastapi-server:
    build: ./server
    environment:
      - DATABASE_URL=postgresql://homework_user:${DB_PASSWORD}@postgres:5432/homework_helper_db
      - JWT_SECRET_KEY=${JWT_SECRET_KEY}
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
```

#### 주요 설정 (app/core/config.py)
```python
class Settings(BaseSettings):
    DATABASE_URL: str                    # PostgreSQL 연결 문자열
    JWT_SECRET_KEY: str                  # JWT 토큰 비밀키
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30일

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_PREFIX: str = "/api/v1"

    CORS_ORIGINS: List[str] = [
        "http://192.168.56.1:8000",      # VM Host PC
        "http://localhost:8000",
    ]

    PROJECT_NAME: str = "HomeworkHelper API"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "Phase 1: VM 로컬 서버"
```

---

## 📊 데이터 모델

### ERD (Entity Relationship Diagram)

```mermaid
erDiagram
    managed_processes ||--o{ process_sessions : "has"

    managed_processes {
        string id PK
        string name
        string monitoring_path
        string launch_path
        string server_reset_time_str
        int user_cycle_hours
        json mandatory_times_str
        bool is_mandatory_time_enabled
        float last_played_timestamp
        string original_launch_path
    }

    process_sessions {
        int id PK
        string process_id FK
        string process_name
        float start_timestamp
        float end_timestamp
        float session_duration
    }

    web_shortcuts {
        string id PK
        string name
        string url
        string refresh_time_str
        float last_reset_timestamp
    }

    global_settings {
        int id PK "fixed=1"
        string sleep_start_time_str
        string sleep_end_time_str
        float sleep_correction_advance_notify_hours
        float cycle_deadline_advance_notify_hours
        bool run_on_startup
        bool lock_window_resize
        bool always_on_top
        bool run_as_admin
        bool notify_on_launch_success
        bool notify_on_launch_failure
        bool notify_on_mandatory_time
        bool notify_on_cycle_deadline
        bool notify_on_sleep_correction
        bool notify_on_daily_reset
    }
```

### 주요 테이블 상세

#### 1. managed_processes
**설명**: 모니터링할 프로세스 정보

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | String (UUID) | 프로세스 고유 ID |
| `name` | String | 표시 이름 (예: "원신") |
| `monitoring_path` | String | 감지할 실행 파일 경로 |
| `launch_path` | String | 실행 버튼 클릭 시 경로 |
| `server_reset_time_str` | String (HH:MM) | 일일 리셋 시간 (nullable) |
| `user_cycle_hours` | Integer | 사용자 주기 (기본 24시간) |
| `mandatory_times_str` | JSON | 필수 플레이 시간 리스트 |
| `is_mandatory_time_enabled` | Boolean | 필수 시간 활성화 여부 |
| `last_played_timestamp` | Float | 마지막 플레이 타임스탬프 (UNIX) |
| `original_launch_path` | String | 원본 실행 경로 (nullable) |

#### 2. process_sessions
**설명**: 프로세스 실행 세션 이력

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | Integer (AI) | 세션 ID |
| `process_id` | String (FK) | 프로세스 ID (managed_processes.id) |
| `process_name` | String | 프로세스 이름 (중복 저장, 성능 향상) |
| `start_timestamp` | Float (Indexed) | 시작 타임스탬프 (UNIX) |
| `end_timestamp` | Float | 종료 타임스탬프 (nullable, 실행 중=NULL) |
| `session_duration` | Float | 세션 길이 (초) |

**인덱스**:
- `process_id`: 프로세스별 세션 조회 최적화
- `process_name`: 이름 기반 조회
- `start_timestamp`: 시간 범위 쿼리 최적화

#### 3. web_shortcuts
**설명**: 웹 바로가기 관리

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | String (UUID) | 바로가기 ID |
| `name` | String | 표시 이름 |
| `url` | String | 웹사이트 URL |
| `refresh_time_str` | String (HH:MM) | 일일 리프레시 시간 (nullable) |
| `last_reset_timestamp` | Float | 마지막 리셋 타임스탬프 |

#### 4. global_settings
**설명**: 전역 설정 (단일 행, id=1 고정)

| 컬럼 그룹 | 컬럼 | 타입 | 설명 |
|-----------|------|------|------|
| **수면 시간** | `sleep_start_time_str` | String | 수면 시작 시간 (기본: "00:00") |
| | `sleep_end_time_str` | String | 수면 종료 시간 (기본: "08:00") |
| | `sleep_correction_advance_notify_hours` | Float | 수면 보정 사전 알림 (기본: 1.0시간) |
| **주기 알림** | `cycle_deadline_advance_notify_hours` | Float | 주기 데드라인 사전 알림 (기본: 2.0시간) |
| **UI 설정** | `run_on_startup` | Boolean | 부팅 시 자동 실행 |
| | `lock_window_resize` | Boolean | 창 크기 고정 |
| | `always_on_top` | Boolean | 항상 위 |
| | `run_as_admin` | Boolean | 관리자 권한 실행 |
| **알림 플래그** | `notify_on_launch_success` | Boolean | 실행 성공 알림 |
| | `notify_on_launch_failure` | Boolean | 실행 실패 알림 |
| | `notify_on_mandatory_time` | Boolean | 필수 시간 알림 |
| | `notify_on_cycle_deadline` | Boolean | 주기 데드라인 알림 |
| | `notify_on_sleep_correction` | Boolean | 수면 보정 알림 |
| | `notify_on_daily_reset` | Boolean | 일일 리셋 알림 |

---

## 🔧 핵심 컴포넌트 상세

### 1. Process Monitor (process_monitor.py)

**역할**: 시스템에서 실행 중인 프로세스를 감지하고 상태 변화를 추적

```python
class ProcessMonitor:
    def __init__(self, data_manager: ProcessesDataPort):
        self.data_manager = data_manager
        self.active_monitored_processes: Dict[str, Dict[str, Any]] = {}
        # key: process_id
        # value: {pid, exe, start_time_approx, session_id}
```

**핵심 메서드**:
- `check_and_update_statuses()`: 프로세스 상태 체크 및 업데이트
  - psutil로 시스템 프로세스 스캔
  - 모니터링 대상 프로세스와 매칭
  - 시작/종료 이벤트 감지
  - 세션 시작/종료 자동 기록

**동작 흐름**:
```
1. psutil.process_iter() → 시스템 프로세스 목록
2. monitoring_path 정규화 및 매칭
3. 신규 프로세스 감지:
   - start_session() 호출
   - active_monitored_processes에 추가
   - 콘솔 로그 출력
4. 프로세스 종료 감지:
   - end_session() 호출
   - last_played_timestamp 업데이트
   - active_monitored_processes에서 제거
```

**프로토콜 (의존성 역전)**:
```python
class ProcessesDataPort(Protocol):
    managed_processes: list[ManagedProcess]
    def update_process(self, updated_process: ManagedProcess) -> bool: ...
    def start_session(self, process_id: str, process_name: str, start_timestamp: float) -> Any: ...
    def end_session(self, session_id: int, end_timestamp: float) -> Any: ...
```

### 2. Scheduler (scheduler.py)

**역할**: 시간 기반 알림 스케줄링

**주요 기능**:
- 서버 리셋 시간 계산
- 필수 플레이 시간 체크
- 주기 데드라인 계산
- 수면 시간 보정

**스케줄링 로직**:
```python
# 예시: 서버 리셋 시간 계산
def calculate_next_reset_time(reset_time_str: str, now: datetime) -> datetime:
    """
    리셋 시간이 "04:00"이고 현재가 03:00이면 → 오늘 04:00 반환
    리셋 시간이 "04:00"이고 현재가 05:00이면 → 내일 04:00 반환
    """
    ...
```

### 3. Notifier (notifier.py)

**역할**: 알림 비즈니스 로직 관리

**알림 타입**:
1. **게임 실행 알림** (launch_success/failure)
2. **필수 플레이 시간 알림** (mandatory_time)
3. **주기 데드라인 알림** (cycle_deadline)
4. **수면 보정 알림** (sleep_correction)
5. **일일 리셋 알림** (daily_reset)

**GUI 통합**:
```python
# gui_notification_handler.py
class GUINotificationHandler:
    def show_notification(self, title: str, message: str):
        """Windows Toast 알림 표시"""
        from windows_toasts import Toast, WindowsToaster
        toaster = WindowsToaster("숙제 관리자")
        toast = Toast()
        toast.text_fields = [title, message]
        toaster.show_toast(toast)
```

### 4. API Client (api_client.py)

**역할**: GUI ↔ FastAPI 서버 통신

**기능**:
- HTTP 요청 래핑
- 에러 핸들링
- 타임아웃 관리
- 응답 캐싱 (선택적)

**예시**:
```python
class ApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url
        self.session = requests.Session()

    def get_processes(self) -> List[Dict]:
        response = self.session.get(f"{self.base_url}/processes")
        response.raise_for_status()
        return response.json()

    def create_session(self, process_id: str, process_name: str, start_timestamp: float):
        data = {
            "process_id": process_id,
            "process_name": process_name,
            "start_timestamp": start_timestamp
        }
        response = self.session.post(f"{self.base_url}/sessions", json=data)
        return response.json()
```

### 5. CRUD Layer (crud.py)

**역할**: 데이터베이스 작업 추상화 + 재시도 로직

**핵심 기능**:
- CRUD 작업 (Create, Read, Update, Delete)
- DB 락 재시도 (최대 3회, 지수 백오프)
- 트랜잭션 관리
- 예외 핸들링

**재시도 로직 예시**:
```python
def create_process(db: Session, process: ProcessCreateSchema, max_retries=3):
    for attempt in range(max_retries):
        try:
            db_process = models.Process(**process.dict())
            db.add(db_process)
            db.commit()
            db.refresh(db_process)
            return db_process
        except OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (2 ** attempt))  # 지수 백오프
                db.rollback()
            else:
                raise
```

---

## 🔄 데이터 흐름

### 1. 프로세스 시작 감지 흐름

```mermaid
flowchart TD
    Start["사용자가 게임 실행"] --> Step1["1. psutil.process_iter()<br/>→ 시스템 프로세스 스캔"]
    Step1 --> Step2["2. ProcessMonitor.check_and_update_statuses()<br/>→ monitoring_path 매칭"]
    Step2 --> Step3["3. 신규 프로세스 감지<br/>→ proc.create_time() 획득"]
    Step3 --> Step4["4. API Client<br/>→ POST /sessions<br/>{ process_id, process_name,<br/>start_timestamp }"]
    Step4 --> Step5["5. FastAPI (main.py)<br/>→ crud.create_session()"]
    Step5 --> Step6["6. Database (SQLite)<br/>INSERT INTO process_sessions<br/>VALUES (id, process_id, process_name,<br/>start_timestamp, NULL, NULL)"]
    Step6 --> Step7["7. active_monitored_processes에 추가<br/>{ pid, exe, start_time_approx, session_id }"]
    Step7 --> Step8["8. 콘솔 로그 출력<br/>[2025-10-29 12:34:56] Process STARTED:<br/>'원신' (PID: 12345, Session ID: 1)"]
```

### 2. 프로세스 종료 감지 흐름

```mermaid
flowchart TD
    Start["사용자가 게임 종료"] --> Step1["1. psutil에서 프로세스 사라짐"]
    Step1 --> Step2["2. ProcessMonitor.check_and_update_statuses()<br/>→ monitoring_path 매칭 실패"]
    Step2 --> Step3["3. active_monitored_processes에서 제거<br/>→ session_id 추출<br/>→ termination_time = time.time()"]
    Step3 --> Step4["4. API Client<br/>→ PUT /sessions/{session_id}/end<br/>{ end_timestamp }"]
    Step4 --> Step5["5. FastAPI (main.py)<br/>→ crud.end_session()"]
    Step5 --> Step6["6. Database (SQLite)<br/>UPDATE process_sessions<br/>SET end_timestamp, session_duration<br/>WHERE id = session_id"]
    Step6 --> Step7["7. last_played_timestamp 업데이트<br/>→ PUT /processes/{process_id}<br/>{ last_played_timestamp }"]
    Step7 --> Step8["8. 콘솔 로그 출력<br/>[2025-10-29 12:35:38] Process STOPPED:<br/>'원신' (Was PID: 12345, Session ID: 1,<br/>Duration: 62.67s)"]
```

### 3. 사용자 인터랙션 흐름

```mermaid
flowchart TD
    Start["사용자 행동"] --> Action1{액션 선택}

    Action1 -->|프로세스 추가<br/>버튼 클릭| Add1["1. dialogs.py<br/>→ AddProcessDialog.show()"]
    Add1 --> Add2["2. 사용자 입력<br/>- 이름, 경로, 리셋 시간 등"]
    Add2 --> Add3["3. API Client<br/>→ POST /processes"]
    Add3 --> Add4["4. Database 저장"]
    Add4 --> Add5["5. main_window.py<br/>→ 테이블 행 추가"]

    Action1 -->|실행 버튼<br/>클릭| Launch1["1. main_window.py<br/>→ launch_selected_process()"]
    Launch1 --> Launch2["2. process_utils.py<br/>→ subprocess.Popen()"]
    Launch2 --> Launch3["3. 성공/실패 알림<br/>→ GUINotificationHandler"]

    Action1 -->|시스템 트레이<br/>아이콘 클릭| Tray1["1. tray_manager.py<br/>→ TrayManager.show_menu()"]
    Tray1 --> Tray2["2. 컨텍스트 메뉴 표시<br/>- 창 표시/숨기기<br/>- 종료"]
```

---

## 🛠️ 기술 스택

### 클라이언트 (데스크톱 앱)

| 카테고리 | 기술 | 버전 | 용도 |
|---------|------|------|------|
| **언어** | Python | 3.13.5 | 메인 런타임 |
| **GUI** | PyQt6 | 6.9.1 | 크로스플랫폼 GUI 프레임워크 |
| **백엔드** | FastAPI | 0.116.2 | RESTful API 서버 (내장) |
| **ORM** | SQLAlchemy | 2.0.43 | 데이터베이스 ORM |
| **데이터베이스** | SQLite | (내장) | 로컬 데이터 저장 |
| **서버** | Uvicorn | 0.35.0 | ASGI 서버 (FastAPI 실행) |
| **검증** | Pydantic | 2.11.9 | 데이터 검증 및 스키마 |
| **프로세스** | psutil | 7.1.0 | 시스템 프로세스 모니터링 |
| **HTTP** | requests | 2.32.5 | HTTP 클라이언트 |
| **알림** | Windows-Toasts | 1.3.1 | Windows 10/11 Toast 알림 |
| **빌드** | PyInstaller | 6.16.0 | 실행 파일 패키징 |
| **설치 관리자** | Inno Setup | 6.x | Windows 설치 관리자 생성 |

### 서버 (Docker/VM)

| 카테고리 | 기술 | 버전 | 용도 |
|---------|------|------|------|
| **언어** | Python | 3.13.5 | 메인 런타임 |
| **백엔드** | FastAPI | 0.116+ | RESTful API 서버 |
| **데이터베이스** | PostgreSQL | 15-alpine | 관계형 데이터베이스 |
| **ORM** | SQLAlchemy | 2.0.35+ | 데이터베이스 ORM |
| **마이그레이션** | Alembic | 1.13+ | DB 스키마 버전 관리 |
| **인증** | python-jose | 3.3+ | JWT 토큰 생성/검증 |
| **비밀번호** | passlib | 1.7.4+ | bcrypt 해싱 |
| **환경 설정** | python-dotenv | 1.0+ | .env 파일 로드 |
| **컨테이너** | Docker | 24+ | 컨테이너화 |
| **오케스트레이션** | Docker Compose | 2.x | 다중 컨테이너 관리 |
| **웹 서버** | Nginx | alpine (Phase 2) | 리버스 프록시, SSL/TLS |

### 개발 도구

| 도구 | 용도 |
|------|------|
| **Git** | 버전 관리 (Git Flow) |
| **VS Code** | IDE |
| **Postman** | API 테스트 |
| **DB Browser for SQLite** | SQLite 데이터베이스 관리 |
| **DBeaver** | PostgreSQL 데이터베이스 관리 |

---

## 🎨 설계 패턴 및 원칙

### 1. 아키텍처 패턴

#### Layered Architecture (계층형 아키텍처)
```
Presentation Layer  → Business Logic Layer  → Data Access Layer
     (GUI)                (Services)              (Database)
```

**적용 이유**:
- 관심사 분리 (Separation of Concerns)
- 각 레이어는 하위 레이어에만 의존
- 레이어별 독립적인 테스트 가능

#### Repository Pattern
```python
# crud.py에서 구현
def get_processes(db: Session) -> List[models.Process]:
    """프로세스 목록 조회"""
    return db.query(models.Process).all()

def create_process(db: Session, process: ProcessCreateSchema):
    """프로세스 추가"""
    db_process = models.Process(**process.dict())
    db.add(db_process)
    db.commit()
    return db_process
```

**적용 이유**:
- 데이터 액세스 로직 추상화
- 데이터베이스 교체 용이 (SQLite ↔ PostgreSQL)

#### Dependency Injection
```python
# FastAPI의 Depends를 활용
@app.get("/processes")
def get_all_processes(db: Session = Depends(get_db)):
    return crud.get_processes(db)
```

**적용 이유**:
- 의존성 관리 자동화
- 테스트 시 Mock 객체 주입 가능

### 2. 디자인 패턴

#### Protocol (의존성 역전 원칙)
```python
# process_monitor.py:9-13
class ProcessesDataPort(Protocol):
    managed_processes: list[ManagedProcess]
    def update_process(self, updated_process: ManagedProcess) -> bool: ...
    def start_session(self, process_id: str, ...) -> Any: ...
```

**적용 이유**:
- 구체적 구현이 아닌 인터페이스에 의존
- ProcessMonitor는 DataManager의 구체적 구현을 몰라도 됨
- 테스트 시 Mock 구현 가능

#### Singleton Pattern
```python
# global_settings 테이블 (id=1 고정)
# instance_manager.py의 SingleInstanceApplication
```

**적용 이유**:
- 전역 설정은 단일 인스턴스만 필요
- 중복 앱 실행 방지 (Windows Mutex)

#### Observer Pattern
```python
# GUI 업데이트 시 PyQt6 Signal/Slot 활용
process_added.connect(update_table)
process_removed.connect(update_table)
```

**적용 이유**:
- 이벤트 기반 아키텍처
- GUI와 비즈니스 로직 분리

### 3. SOLID 원칙 적용

#### Single Responsibility Principle (단일 책임 원칙)
- `process_monitor.py`: 프로세스 감지만 담당
- `scheduler.py`: 스케줄링 로직만 담당
- `notifier.py`: 알림 비즈니스 로직만 담당

#### Open/Closed Principle (개방-폐쇄 원칙)
- 새로운 알림 타입 추가 시 기존 코드 수정 없이 확장 가능

#### Liskov Substitution Principle (리스코프 치환 원칙)
- `ProcessesDataPort` 프로토콜을 구현한 어떤 객체도 ProcessMonitor에 주입 가능

#### Interface Segregation Principle (인터페이스 분리 원칙)
- `ProcessesDataPort`는 ProcessMonitor가 필요한 메서드만 정의

#### Dependency Inversion Principle (의존성 역전 원칙)
- ProcessMonitor는 구체적 DataManager가 아닌 Protocol에 의존

---

## 🔒 보안 및 안정성

### 1. 데이터 안전성

#### WAL (Write-Ahead Logging) 모드
```python
# database.py:49-59
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=FULL")
    cursor.execute("PRAGMA wal_autocheckpoint=20")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA cache_size=-64000")
    cursor.close()
```

**장점**:
- 동시 읽기/쓰기 지원 (GUI + API 서버)
- 데이터 손실 방지 (synchronous=FULL)
- 성능 향상 (64MB 캐시)

#### Graceful Shutdown
```python
# homework_helper.pyw:330-364
def shutdown_handler(signum, frame):
    logger.info("서버 종료 신호 수신. 안전하게 종료합니다...")

    # 1. WAL checkpoint 수행
    with engine.connect() as conn:
        conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    # 2. 데이터베이스 연결 종료
    engine.dispose()

    # 3. Mutex 해제
    win32api.CloseHandle(server_mutex)

    # 4. PID 파일 삭제
    os.remove(pid_file)
```

**보장**:
- .wal 파일 내용을 .db로 완전 이동
- 데이터 무결성 보장
- 깨끗한 종료

#### 자동 재시도 로직
```python
# crud.py 패턴
for attempt in range(max_retries):
    try:
        # DB 작업 수행
        db.commit()
        return result
    except OperationalError as e:
        if "database is locked" in str(e):
            time.sleep(0.1 * (2 ** attempt))  # 지수 백오프
            db.rollback()
        else:
            raise
```

**처리**:
- DB 락 발생 시 최대 3회 재시도
- 0.1초 → 0.2초 → 0.4초 지수 백오프

### 2. 프로세스 안정성

#### 단일 인스턴스 보장
```python
# instance_manager.py
# Windows Named Mutex 사용
mutex_name = "Global\\HomeworkHelperMutex"
mutex = win32event.CreateMutex(None, False, mutex_name)
```

**보장**:
- 한 번에 하나의 앱 인스턴스만 실행
- IPC를 통해 기존 인스턴스 활성화

#### 독립 API 서버 프로세스
```python
# homework_helper.pyw:192-196
api_server_process = multiprocessing.Process(
    target=run_server_main,
    daemon=True  # GUI 종료 시 자동 종료
)
```

**장점**:
- GUI 크래시 시 API 서버는 영향 없음
- 서버 크래시 시 GUI는 영향 없음
- 독립적인 로깅 및 에러 핸들링

### 3. 에러 핸들링

#### 프로세스 모니터링
```python
# process_monitor.py:76-79
except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
    print(f"'{managed_proc.name}' 시작 정보 가져오는 중 오류: {e}")
    if managed_proc.id in self.active_monitored_processes:
        self.active_monitored_processes.pop(managed_proc.id)
```

**처리**:
- psutil 예외 처리
- 프로세스 액세스 권한 부족 시 graceful degradation

#### API 클라이언트
```python
# api_client.py 패턴
try:
    response = self.session.get(url)
    response.raise_for_status()
    return response.json()
except requests.ConnectionError:
    # 서버 연결 실패 시 로컬 캐시 반환
    return cached_data
except requests.Timeout:
    # 타임아웃 처리
    return default_value
```

---

## 🚀 확장 계획

### Phase 1: 로컬 앱 안정화 (완료)
- ✅ PyQt6 GUI
- ✅ 프로세스 모니터링
- ✅ SQLite + WAL 모드
- ✅ FastAPI 내장 서버
- ✅ Windows Toast 알림
- ✅ 세션 트래킹

### Phase 2: VM 로컬 서버 (진행 중)
- ✅ Docker Compose 설정
- ✅ FastAPI 서버 초기 설정
- ⏳ PostgreSQL 연동
- ⏳ JWT 인증 구현
- ⏳ API 엔드포인트 확장
- ⏳ Android 앱 연동 준비 (CORS)

### Phase 3: 클라우드 확장 (계획)
- ⬜ AWS/GCP/Azure 배포
- ⬜ Redis 캐싱
- ⬜ Nginx 리버스 프록시
- ⬜ SSL/TLS 인증서
- ⬜ 로드 밸런싱
- ⬜ 모니터링 (Prometheus + Grafana)

### Phase 4: 멀티 플랫폼 (장기)
- ⬜ Android 앱 개발
- ⬜ iOS 앱 개발 (선택)
- ⬜ 웹 대시보드
- ⬜ 실시간 동기화 (WebSocket)
- ⬜ 푸시 알림 (FCM)

---

## 📚 참고 자료

### 내부 문서
- [`README.md`](../README.md): 프로젝트 전체 개요
- [`BUILD_GUIDE.md`](../BUILD_GUIDE.md): 빌드 및 배포 가이드
- [`docs/dev-setup-guide.md`](./dev-setup-guide.md): 개발 환경 설정
- [`docs/git-workflow.md`](./git-workflow.md): Git 워크플로우
- [`docs/vm-server-architecture.md`](./vm-server-architecture.md): VM 서버 아키텍처 (Phase 2)

### 외부 자료
- [FastAPI 공식 문서](https://fastapi.tiangolo.com/)
- [PyQt6 공식 문서](https://www.riverbankcomputing.com/static/Docs/PyQt6/)
- [SQLAlchemy 공식 문서](https://docs.sqlalchemy.org/)
- [SQLite WAL 모드 설명](https://www.sqlite.org/wal.html)
- [psutil 문서](https://psutil.readthedocs.io/)

---

## 🙋 FAQ

### Q1. 왜 SQLite와 PostgreSQL을 동시에 사용하나요?
**A**: 로컬 앱은 간편한 SQLite를 사용하고, 원격 서버는 다중 클라이언트 지원을 위해 PostgreSQL을 사용합니다.

### Q2. API 서버가 GUI와 독립 프로세스로 실행되는 이유는?
**A**: GUI 크래시 시에도 데이터베이스 무결성을 보장하고, 서버가 독립적으로 graceful shutdown을 수행하기 위함입니다.

### Q3. WAL 모드의 단점은 없나요?
**A**: .wal 파일이 추가로 생성되어 디스크 공간을 차지하지만, 주기적인 checkpoint로 관리됩니다. 성능과 안정성 향상이 더 큽니다.

### Q4. 프로세스 모니터링 주기는 어떻게 되나요?
**A**: 기본적으로 1초마다 스캔하지만, 설정에서 변경 가능합니다.

### Q5. 다른 OS(Linux, macOS)에서도 실행 가능한가요?
**A**: 현재는 Windows 전용입니다. psutil은 크로스플랫폼이지만, Windows Toast 알림, 트레이 아이콘 등은 Windows 전용입니다. 추후 확장 가능합니다.

---

## 📝 변경 이력

| 날짜 | 버전 | 변경 내용 |
|------|------|-----------|
| 2025-10-29 | 1.0.0 | 초기 아키텍처 문서 작성 |

---

**문서 작성자**: Claude (AI Assistant)
**리뷰 요청**: Gemini CLI로 검토 예정
**관리자**: lsh930309

---

**📌 이 문서를 정기적으로 업데이트하여 코드베이스와 동기화하세요!**
