# 📚 Homework Helper

<div align="center">

![Python Version](https://img.shields.io/badge/Python-3.13.5-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.116.2-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0.43-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)
![PyQt6](https://img.shields.io/badge/PyQt6-6.9.1-41CD52?style=for-the-badge&logo=qt&logoColor=white)

[![Download Latest Release](https://img.shields.io/badge/Download-Latest_Release-4CAF50?style=for-the-badge&logo=github&logoColor=white)](https://github.com/lsh930309/HomeworkHelperServer/releases/latest)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

**게임 및 웹 일일 루틴을 자동으로 관리하고 추적하는 스마트 도우미**

[특징](#-주요-기능) • [설치](#-설치-방법) • [사용법](#-사용-가이드) • [API 문서](#-api-문서)

</div>

---

## 📖 프로그램 목적

Homework Helper는 게임과 웹사이트의 **일일 루틴 관리**를 자동화하는 Windows용 애플리케이션입니다.

### 🎯 해결하는 문제

- 🎮 **게임 일일 퀘스트 놓침** - 서버 리셋 시간과 사용자 주기를 추적하여 알림
- ⏰ **플레이 시간 관리** - 마지막 플레이 시간 자동 기록 및 데드라인 알림
- 🌐 **웹 루틴 잊음** - 매일 방문해야 하는 사이트 자동 추적
- 📊 **게임 패턴 분석** - 세션별 플레이 타임 자동 수집 및 통계

---

## ✨ 주요 기능

### 🎮 프로세스 모니터링 및 자동 실행
- 게임/프로그램 실행 상태 실시간 감지
- 원클릭 실행 버튼 제공
- 프로세스 시작/종료 자동 감지 및 기록
- **세션 타임스탬프 자동 트래킹** (시작/종료/플레이 시간)

### ⏰ 스마트 알림 시스템
- **서버 리셋 시간 추적** - 일일 퀘스트 리셋 시간 설정
- **사용자 주기 설정** - 24시간 단위 커스텀 주기 관리
- **필수 플레이 시간** - 특정 시간대 플레이 필수 알림
- **수면 시간 보정** - 취침 중 알림 방지

### 🌐 웹 바로가기 관리
- 일일 리프레시가 필요한 웹사이트 등록
- 리셋 시간 설정 및 자동 추적
- 원클릭 브라우저 실행

### 📊 데이터 트래킹 및 분석
- **세션 기반 플레이 기록** - 게임별 실행 시작/종료 타임스탬프
- **플레이 패턴 분석** - 프로세스별 세션 이력 및 통계
- **SQLite 데이터베이스** - WAL 모드로 안전한 데이터 저장
- **RESTful API** - FastAPI 기반 데이터 조회/분석 인터페이스

### 🔧 시스템 기능
- 시스템 트레이 상주 모드
- 부팅 시 자동 실행 (선택)
- 관리자 권한 실행 지원
- 알림별 On/Off 설정

---

## 🚀 설치 방법

### Option 1: 실행 파일 다운로드 (권장)

1. [최신 릴리즈 다운로드](https://github.com/lsh930309/HomeworkHelperServer/releases/latest)
2. `homework_helper.exe` 실행
3. 첫 실행 시 `homework_helper_data` 폴더 자동 생성

### Option 2: 소스코드 실행

```bash
# 1. 저장소 클론
git clone https://github.com/lsh930309/HomeworkHelperServer.git
cd HomeworkHelperServer

# 2. 가상환경 생성 (선택)
python -m venv venv
venv\Scripts\activate  # Windows

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 프로그램 실행
python homework_helper.pyw
```

---

## 📖 사용 가이드

### 1️⃣ 프로세스 추가하기

<details>
<summary><b>게임/프로그램 등록 방법</b></summary>

1. **메인 화면에서 `프로세스 추가` 버튼 클릭**
2. **필수 정보 입력:**
   - 📝 **이름**: 표시될 프로세스 이름
   - 📂 **모니터링 경로**: 프로세스 실행 파일 경로 (감지용)
   - 🚀 **실행 경로**: 버튼 클릭 시 실행할 파일 경로

3. **선택 정보 입력:**
   - 🔄 **서버 리셋 시간**: 일일 퀘스트가 리셋되는 시간 (예: 04:00)
   - ⏱️ **사용자 주기**: 플레이 주기 (기본 24시간)
   - ⭐ **필수 플레이 시간**: 특정 시간대에 플레이 필수 (여러 개 설정 가능)

4. **저장 완료** - 프로세스가 자동 모니터링 시작

</details>

### 2️⃣ 웹 바로가기 추가하기

<details>
<summary><b>일일 웹사이트 등록 방법</b></summary>

1. **`웹 바로가기 추가` 버튼 클릭**
2. **정보 입력:**
   - 📝 **이름**: 바로가기 이름
   - 🌐 **URL**: 웹사이트 주소
   - 🔄 **리프레시 시간**: 일일 리셋 시간 (선택)

3. **저장** - 원클릭 실행 버튼 생성

</details>

### 3️⃣ 알림 설정하기

<details>
<summary><b>알림 커스터마이징</b></summary>

1. **설정(⚙️) 버튼 클릭**
2. **알림 옵션 선택:**
   - ✅ 게임 실행 성공/실패 알림
   - ✅ 필수 플레이 시간 알림
   - ✅ 주기 데드라인 알림
   - ✅ 수면 시간 보정 알림
   - ✅ 일일 리셋 알림

3. **수면 시간 설정:**
   - 시작 시간 / 종료 시간 설정
   - 수면 중 알림을 기상 후로 연기

</details>

### 4️⃣ 세션 데이터 조회하기

<details>
<summary><b>플레이 기록 분석</b></summary>

**API 엔드포인트 사용:**

```bash
# FastAPI 서버가 자동으로 백그라운드에서 실행됩니다.
# 브라우저에서 http://127.0.0.1:8000/docs 접속

# 1. 모든 세션 조회
GET http://127.0.0.1:8000/sessions

# 2. 특정 게임의 세션 이력
GET http://127.0.0.1:8000/sessions/process/{process_id}

# 3. 현재 활성 세션 확인
GET http://127.0.0.1:8000/sessions/process/{process_id}/active
```

**응답 예시:**
```json
[
  {
    "id": 1,
    "process_id": "6d101682-c386-4a1c-8696-3d4d5f85cf09",
    "process_name": "젠레스 존 제로",
    "start_timestamp": 1759405875.473616,
    "end_timestamp": 1759405938.1449769,
    "session_duration": 62.67
  }
]
```

</details>

---

## 🎓 튜토리얼: 첫 게임 등록하기

### 예시: 원신(Genshin Impact) 등록

1. **프로세스 추가 버튼 클릭**

2. **정보 입력:**
   ```
   이름: 원신
   모니터링 경로: C:\Program Files\Genshin Impact\Genshin Impact Game\GenshinImpact.exe
   실행 경로: C:\Program Files\Genshin Impact\launcher.exe
   서버 리셋 시간: 04:00
   사용자 주기: 24시간
   ```

3. **필수 플레이 시간 추가 (선택):**
   - `필수 시간 활성화` 체크
   - `21:00` 추가 (저녁 9시에 일일 퀘스트 알림)

4. **저장 완료**
   - 원신이 실행되면 자동으로 감지
   - 세션 시작/종료 시간 자동 기록
   - 리셋 2시간 전 알림 받기

---

## 📡 API 문서

### 기본 정보

- **Base URL**: `http://127.0.0.1:8000` (로컬 서버 자동 시작)
- **Interactive Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **OpenAPI Schema**: [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json)

### 주요 엔드포인트

#### 프로세스 관리
```http
GET    /processes              # 모든 프로세스 조회
GET    /processes/{id}         # 특정 프로세스 조회
POST   /processes              # 프로세스 추가
PUT    /processes/{id}         # 프로세스 수정
DELETE /processes/{id}         # 프로세스 삭제
```

#### 세션 트래킹
```http
POST   /sessions                          # 세션 시작 기록
PUT    /sessions/{session_id}/end         # 세션 종료 기록
GET    /sessions                          # 모든 세션 조회
GET    /sessions/process/{process_id}     # 프로세스별 세션 이력
GET    /sessions/process/{process_id}/active  # 활성 세션 조회
```

#### 웹 바로가기
```http
GET    /shortcuts              # 모든 바로가기 조회
POST   /shortcuts              # 바로가기 추가
PUT    /shortcuts/{id}         # 바로가기 수정
DELETE /shortcuts/{id}         # 바로가기 삭제
```

#### 설정
```http
GET    /settings               # 전역 설정 조회
PUT    /settings               # 전역 설정 수정
```

---

## 🛠️ 기술 스택

### 핵심 라이브러리

| 라이브러리 | 버전 | 용도 |
|----------|------|------|
| **Python** | 3.13.5 | 메인 런타임 |
| **FastAPI** | 0.116.2 | RESTful API 서버 |
| **SQLAlchemy** | 2.0.43 | ORM 및 데이터베이스 관리 |
| **PyQt6** | 6.9.1 | GUI 프레임워크 |
| **psutil** | 7.1.0 | 프로세스 모니터링 |
| **uvicorn** | 0.35.0 | ASGI 서버 |
| **Pydantic** | 2.11.9 | 데이터 검증 |
| **requests** | 2.32.5 | HTTP 클라이언트 |

### 아키텍처

```
┌─────────────────────────────────────────┐
│         PyQt6 GUI (frontend)            │
│   - 트레이 아이콘, 메인 윈도우, 알림     │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│      API Client (api_client.py)         │
│   - HTTP 요청 관리, 데이터 캐싱          │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│    FastAPI Server (main.py)             │
│   - RESTful API, 자동 문서화             │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│      CRUD Layer (crud.py)               │
│   - 비즈니스 로직, DB 재시도 로직        │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│   Database (SQLite + WAL Mode)          │
│   - 프로세스, 세션, 설정 저장            │
└─────────────────────────────────────────┘

         ┌─────────────────┐
         │ Process Monitor │ ◄── psutil
         │  (백그라운드)    │
         └─────────────────┘
```

---

## 🔒 데이터 안전성

### 구현된 보호 장치

1. **WAL (Write-Ahead Logging) 모드**
   - 동시 읽기/쓰기 지원
   - 데이터 손실 방지

2. **자동 재시도 로직**
   - DB 락 발생 시 최대 3회 재시도
   - 지수 백오프 적용

3. **예외 처리**
   - `OperationalError`, `IntegrityError` 핸들링
   - 로깅 시스템 통합

4. **트랜잭션 관리**
   - SQLAlchemy 세션 자동 관리
   - 실패 시 자동 롤백

---

## 📁 프로젝트 구조

```
HomeworkHelperServer/
├── homework_helper.pyw       # 메인 애플리케이션 진입점
├── main.py                   # FastAPI 서버
├── api_client.py             # API 클라이언트
├── database.py               # DB 설정 (WAL 모드)
├── models.py                 # SQLAlchemy 모델
├── schemas.py                # Pydantic 스키마
├── crud.py                   # CRUD 로직 (재시도 포함)
├── process_monitor.py        # 프로세스 모니터링
├── data_models.py            # 도메인 모델
├── notifier.py               # 알림 시스템
├── scheduler.py              # 스케줄링 로직
├── dialogs.py                # PyQt6 다이얼로그
├── requirements.txt          # 의존성 목록
└── homework_helper_data/     # 데이터 디렉토리 (자동 생성)
    └── app_data.db          # SQLite 데이터베이스
```

---

## 🤝 기여하기

기여는 언제나 환영합니다!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

---

## 📧 문의

프로젝트 관련 문의사항이나 버그 제보는 [Issues](https://github.com/lsh930309/HomeworkHelperServer/issues) 페이지를 이용해주세요.

---

<div align="center">

**Made with ❤️ for gamers who never miss daily quests**

⭐ 이 프로젝트가 도움이 되었다면 Star를 눌러주세요!

</div>
