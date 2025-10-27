# 개발 환경 세팅 가이드 (멀티 PC)

**프로젝트**: HomeworkHelper
**작성일**: 2025-10-27
**버전**: v1.0

---

## 개요

이 문서는 **여러 PC에서 개발을 진행**할 때 동일한 환경을 재현하고 Claude Code 작업을 이어서 할 수 있도록 안내합니다.

---

## 🖥️ 지원 환경

- **OS**: Windows 10/11, macOS, Linux
- **Python**: 3.11 이상 (권장: 3.11 또는 3.13)
- **Git**: 2.30 이상 (Git LFS 포함)
- **Claude Code**: 최신 버전
- **Gemini CLI**: 최신 버전 (협업용)

---

## 📋 새 PC에서 프로젝트 시작하기

### 1️⃣ 필수 소프트웨어 설치

#### Python 설치
```bash
# Windows
# https://www.python.org/downloads/
# 설치 시 "Add Python to PATH" 체크

# macOS (Homebrew)
brew install python@3.11

# Linux (Ubuntu/Debian)
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip
```

**설치 확인**:
```bash
python --version  # Python 3.11.x 또는 3.13.x
pip --version
```

#### Git 및 Git LFS 설치
```bash
# Windows
# https://git-scm.com/download/win (Git LFS 포함)

# macOS
brew install git git-lfs

# Linux
sudo apt install git git-lfs

# Git LFS 초기화
git lfs install
```

#### Claude Code 설치
```bash
# 설치 방법은 Claude Code 공식 문서 참조
# https://docs.claude.com/en/docs/claude-code
```

#### Gemini CLI 설치
```bash
# Gemini CLI 설치 (협업용)
# 설치 방법은 Gemini 공식 문서 참조
```

---

### 2️⃣ 프로젝트 클론 및 초기 설정

```bash
# 1. 프로젝트 클론
git clone https://github.com/lsh930309/HomeworkHelperServer.git
cd HomeworkHelperServer

# 2. develop 브랜치로 전환 (최신 개발 버전)
git checkout develop

# 3. 전체 히스토리 확인
git log --oneline --graph --all --decorate

# 4. 서브모듈 초기화 (있는 경우)
git submodule update --init --recursive
```

---

### 3️⃣ Python 가상 환경 설정

**⚠️ 중요**: 각 PC에서 독립적인 가상 환경을 구축합니다.

```bash
# 1. 가상 환경 생성
python -m venv .venv

# 2. 가상 환경 활성화
# Windows (CMD)
.venv\Scripts\activate.bat

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate

# 3. pip 업그레이드
pip install --upgrade pip

# 4. 의존성 설치 (현재는 Phase 0 PC 클라이언트용)
pip install -r requirements.txt

# (Phase 1 서버 개발 시 추가)
# pip install -r server/requirements.txt
```

**가상 환경 확인**:
```bash
which python  # macOS/Linux
where python  # Windows
# .venv 경로가 출력되어야 함
```

---

### 4️⃣ Claude Code 프로젝트 설정

#### `.claude/settings.local.json` 생성

프로젝트에는 `.claude/settings.json` (공통 설정)이 Git에 포함되어 있습니다.
**개인별 로컬 설정**은 `.claude/settings.local.json`에 작성하세요.

**Windows PC용 예시**:
```json
{
  "permissions": {
    "allow": [
      "Read(//c/Users/YOUR_USERNAME/.claude/**)",
      "Read(//c/**)"
    ]
  }
}
```

**macOS/Linux PC용 예시**:
```json
{
  "permissions": {
    "allow": [
      "Read(/Users/YOUR_USERNAME/.claude/**)",
      "Read(/home/YOUR_USERNAME/**)"
    ]
  }
}
```

**⚠️ 주의**:
- `YOUR_USERNAME`을 실제 사용자 이름으로 변경하세요.
- 이 파일은 Git에 커밋되지 않습니다 (`.gitignore`에 등록됨).

---

### 5️⃣ 전역 Claude 설정 복사 (선택)

**다른 PC에서 동일한 Gemini 협업 프로토콜을 사용하려면**:

```bash
# 현재 PC의 전역 설정 위치
# Windows: C:\Users\YOUR_USERNAME\.claude\CLAUDE.md
# macOS: /Users/YOUR_USERNAME/.claude/CLAUDE.md
# Linux: /home/YOUR_USERNAME/.claude/CLAUDE.md

# 1. 현재 PC에서 내보내기 (Git으로 관리하지 않음)
# 프로젝트 docs 폴더에 백업 복사 (참고용, Git에 포함하지 않음)
cp ~/.claude/CLAUDE.md ./docs/CLAUDE.md.backup  # macOS/Linux
copy C:\Users\korea\.claude\CLAUDE.md docs\CLAUDE.md.backup  # Windows

# 2. 새 PC에서 가져오기
# docs/CLAUDE.md.backup 내용을 새 PC의 ~/.claude/CLAUDE.md로 복사
```

**⚠️ 주의**: `CLAUDE.md`는 사용자별 전역 설정이므로 Git에 포함하지 않습니다. 필요 시 수동으로 복사하세요.

---

### 6️⃣ 환경 변수 설정 (Phase 1 서버 개발 시)

```bash
# server/.env.example을 복사하여 .env 생성
cd server
cp .env.example .env

# .env 파일 편집 (실제 값 입력)
nano .env  # 또는 vscode, notepad 등

# 필수 값:
# - DATABASE_URL
# - JWT_SECRET_KEY (openssl rand -hex 32로 생성)
# - DB_PASSWORD
```

---

### 7️⃣ 작업 시작 전 최신 코드 동기화

```bash
# 1. 현재 브랜치 확인
git branch

# 2. develop 브랜치 최신화
git checkout develop
git pull origin develop

# 3. 새 feature 브랜치 생성 (작업 시작 시)
git checkout -b feature/your-feature-name

# 4. 작업 후 커밋 및 push
git add .
git commit -m "feat: your feature description"
git push -u origin feature/your-feature-name
```

---

## 🔄 PC 간 작업 전환 체크리스트

### PC A에서 작업 종료 시
- [ ] 모든 변경사항 커밋
  ```bash
  git status  # 변경사항 확인
  git add .
  git commit -m "작업 내용"
  ```
- [ ] 원격 저장소에 push
  ```bash
  git push origin your-branch-name
  ```
- [ ] 가상 환경 비활성화
  ```bash
  deactivate
  ```

### PC B에서 작업 시작 시
- [ ] 최신 코드 pull
  ```bash
  git checkout your-branch-name
  git pull origin your-branch-name
  ```
- [ ] 가상 환경 활성화
  ```bash
  # Windows
  .venv\Scripts\activate

  # macOS/Linux
  source .venv/bin/activate
  ```
- [ ] 의존성 업데이트 (필요 시)
  ```bash
  pip install -r requirements.txt
  ```
- [ ] Claude Code로 작업 이어가기
  ```bash
  # Claude Code를 열고 프로젝트 디렉토리에서 시작
  ```

---

## 🛠️ 문제 해결

### 1. "command not found: python" 오류
```bash
# python3 사용 (macOS/Linux)
python3 --version

# alias 설정 (선택)
echo "alias python=python3" >> ~/.bashrc  # Linux
echo "alias python=python3" >> ~/.zshrc  # macOS
```

### 2. Git LFS 파일이 제대로 다운로드되지 않음
```bash
# Git LFS 파일 강제 다운로드
git lfs pull
```

### 3. 가상 환경 활성화 오류 (Windows PowerShell)
```powershell
# 실행 정책 변경 (관리자 권한)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 4. Claude Code 권한 오류
- `.claude/settings.local.json` 파일의 경로가 올바른지 확인
- 절대 경로 사용 (`//c/...` 또는 `/Users/...`)

### 5. Python 버전 불일치
```bash
# PC A: Python 3.11
# PC B: Python 3.13

# 해결책 1: 동일한 버전 설치 (권장)
# 해결책 2: pyenv 사용하여 버전 관리
# https://github.com/pyenv/pyenv
```

---

## 📦 의존성 관리 (향후)

### Phase 1 서버 개발 시
```bash
# 서버 의존성 설치
pip install -r server/requirements.txt

# 새 패키지 추가 후
pip freeze > server/requirements.txt
git add server/requirements.txt
git commit -m "chore: update server dependencies"
```

### Phase 1 Android 개발 시
```bash
# Android Studio에서 Gradle Sync 자동 수행
# build.gradle 파일이 Git에 포함되어 있음
```

---

## 🔐 보안 주의사항

### Git에 커밋하지 말아야 할 것
- `.env` 파일 (환경 변수, 비밀 키)
- `.claude/settings.local.json` (개인별 경로)
- 데이터베이스 파일 (`*.db`, `*.sqlite`)
- 빌드 결과물 (`dist/`, `build/`, `*.apk`, `*.exe`)

### Git에 커밋해야 할 것
- `.claude/settings.json` (프로젝트 공통 설정)
- `requirements.txt` (의존성 목록)
- `.env.example` (환경 변수 템플릿)
- `docs/` (문서)

---

## 🎯 빠른 세팅 체크리스트

### 새 PC 초기 세팅 (30분 이내)
- [ ] Python 3.11+ 설치
- [ ] Git + Git LFS 설치
- [ ] Claude Code 설치
- [ ] Gemini CLI 설치 (선택)
- [ ] 프로젝트 클론: `git clone ...`
- [ ] 가상 환경 생성: `python -m venv .venv`
- [ ] 가상 환경 활성화
- [ ] 의존성 설치: `pip install -r requirements.txt`
- [ ] `.claude/settings.local.json` 생성
- [ ] (선택) 전역 CLAUDE.md 복사

### 작업 전 일일 체크리스트 (2분)
- [ ] `git pull origin develop` (최신화)
- [ ] 가상 환경 활성화
- [ ] Claude Code 실행

---

## 📞 도움이 필요할 때

### Git 관련
```bash
# 변경사항 확인
git status

# 로그 확인
git log --oneline --graph

# 브랜치 확인
git branch -a

# 충돌 해결 가이드
# docs/git-workflow.md 참조
```

### Claude Code 관련
```bash
# Claude Code 문서
# https://docs.claude.com/en/docs/claude-code

# 프로젝트 설정 확인
cat .claude/settings.json
cat .claude/settings.local.json
```

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-10-27
**관련 문서**:
- `git-workflow.md` - Git 브랜치 전략
- `vm-server-architecture.md` - VM 서버 설정
