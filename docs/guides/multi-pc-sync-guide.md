# 🔄 멀티 PC 동기화 퀵 가이드

**HomeworkHelper 프로젝트를 여러 PC에서 개발할 때 필수 체크리스트**

---

## 🆕 새 PC에서 처음 시작할 때 (15분)

### 1. 필수 소프트웨어 설치
```bash
# 체크리스트
- [ ] Python 3.11+ (python --version 확인)
- [ ] Git + Git LFS (git lfs install)
- [ ] Claude Code
- [ ] (선택) Gemini CLI
```

### 2. 프로젝트 클론
```bash
git clone https://github.com/lsh930309/HomeworkHelperServer.git
cd HomeworkHelperServer
git checkout develop
```

### 3. Python 가상 환경
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Claude 로컬 설정 생성
**Windows**:
```powershell
# .claude/settings.local.json 생성
@"
{
  "permissions": {
    "allow": [
      "Read(//c/Users/$env:USERNAME/.claude/**)",
      "Read(//c/**)"
    ]
  }
}
"@ | Out-File -FilePath .claude/settings.local.json -Encoding utf8
```

**macOS/Linux**:
```bash
cat > .claude/settings.local.json << 'EOF'
{
  "permissions": {
    "allow": [
      "Read($HOME/.claude/**)",
      "Read($HOME/**)"
    ]
  }
}
EOF
```

### 5. 전역 Claude 설정 복사 (선택)
```bash
# 기존 PC에서 내보내기
# C:\Users\korea\.claude\CLAUDE.md → 새 PC의 동일 경로로 복사
# (Gemini 협업 프로토콜 포함)
```

---

## 🔁 PC 간 작업 전환 (2분)

### PC A에서 작업 종료
```bash
# 1. 모든 변경사항 확인
git status

# 2. 커밋 및 push
git add .
git commit -m "작업 내용"
git push origin your-branch-name

# 3. 가상 환경 비활성화
deactivate
```

### PC B에서 작업 재개
```bash
# 1. 최신 코드 받기
git pull origin your-branch-name

# 2. 가상 환경 활성화
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

# 3. (필요 시) 의존성 업데이트
pip install -r requirements.txt

# 4. Claude Code 열기
# 작업 이어서 시작!
```

---

## 📋 일일 작업 시작 체크리스트 (1분)

```bash
# 1. develop 브랜치 최신화
git checkout develop
git pull origin develop

# 2. feature 브랜치로 전환 (또는 생성)
git checkout feature/your-branch-name
# 또는
git checkout -b feature/new-feature

# 3. 가상 환경 활성화
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

# 4. Claude Code 실행
```

---

## ⚠️ 주의사항

### ✅ Git에 커밋해야 할 것
- `.claude/settings.json` (공통 권한)
- `.claude/README.md` (설명서)
- `requirements.txt` (의존성)
- `.env.example` (환경 변수 템플릿)
- 모든 코드 및 문서

### ❌ Git에 커밋하면 안 되는 것
- `.claude/settings.local.json` (개인별 경로)
- `.env` (민감 정보)
- `.venv/` (가상 환경)
- `*.db`, `*.sqlite` (데이터베이스)
- `dist/`, `build/` (빌드 결과물)

---

## 🆘 트러블슈팅

| 문제 | 해결 |
|------|------|
| "command not found: python" | `python3` 사용 또는 PATH 설정 확인 |
| Git LFS 파일 누락 | `git lfs pull` 실행 |
| Claude 권한 오류 | `.claude/settings.local.json` 경로 확인 |
| 가상 환경 활성화 오류 (Windows) | PowerShell 실행 정책 변경 |

---

## 📖 상세 문서

- **전체 설명**: [`docs/dev-setup-guide.md`](docs/dev-setup-guide.md)
- **Claude 설정**: [`.claude/README.md`](.claude/README.md)
- **Git 워크플로우**: [`docs/git-workflow.md`](docs/git-workflow.md)

---

**TL;DR**:
1. 새 PC: Python + Git LFS 설치 → 클론 → venv → `.claude/settings.local.json` 생성
2. 작업 전환: PC A에서 push → PC B에서 pull + venv 활성화
3. Git에 `.claude/settings.local.json`, `.env`는 커밋 금지!

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-10-27
