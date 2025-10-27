# Claude Code 설정 안내

이 폴더는 HomeworkHelper 프로젝트의 Claude Code 설정을 관리합니다.

---

## 📁 파일 구조

```
.claude/
├── README.md                 # 이 파일 (설명서)
├── settings.json             # 프로젝트 공통 설정 (Git 포함)
└── settings.local.json       # 개인별 로컬 설정 (Git 제외)
```

---

## ⚙️ 설정 파일 설명

### `settings.json` (Git 포함)
**목적**: 프로젝트 팀원 모두가 공유하는 기본 권한 설정

**내용**:
- Python 실행 권한
- Gemini CLI 실행 권한
- Git 명령어 권한
- Docker 명령어 권한 (Phase 1)

**수정 시 주의**:
- 이 파일을 수정하면 모든 팀원에게 영향을 미칩니다.
- 개인별 경로 (`Read(//c/Users/...`)는 추가하지 마세요.
- 변경 후 반드시 Git에 커밋하세요.

### `settings.local.json` (Git 제외)
**목적**: 개인 PC별 로컬 권한 설정 (경로 등)

**내용 예시** (Windows):
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

**내용 예시** (macOS/Linux):
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

**주의**:
- 이 파일은 `.gitignore`에 등록되어 Git에 커밋되지 않습니다.
- 새 PC에서 작업 시 직접 생성해야 합니다.
- `YOUR_USERNAME`을 실제 사용자 이름으로 변경하세요.

---

## 🚀 새 PC에서 설정하기

1. **프로젝트 클론**:
   ```bash
   git clone https://github.com/lsh930309/HomeworkHelperServer.git
   cd HomeworkHelperServer
   ```

2. **`settings.json` 확인** (자동으로 포함됨):
   ```bash
   cat .claude/settings.json
   ```

3. **`settings.local.json` 생성**:
   ```bash
   # Windows (PowerShell)
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

   # macOS/Linux (Bash)
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

4. **Claude Code 실행**:
   ```bash
   # Claude Code에서 프로젝트 디렉토리 열기
   ```

---

## 🔧 권한 설정 가이드

### 기본 권한 (settings.json)
| 권한 | 설명 | 사용 시기 |
|------|------|----------|
| `Bash(python:*)` | Python 스크립트 실행 | PC 클라이언트, 서버 개발 |
| `Bash(gemini:*)` | Gemini CLI 실행 | 코드 검토, 아키텍처 결정 |
| `Bash(git:*)` | Git 명령어 실행 | 커밋, push, merge |
| `Bash(docker:*)` | Docker 명령어 실행 | Phase 1 서버 개발 |

### 로컬 권한 (settings.local.json)
| 권한 | 설명 | 필요 여부 |
|------|------|----------|
| `Read(//c/Users/.../.claude/**)` | 전역 Claude 설정 읽기 | 필수 (Windows) |
| `Read(/Users/.../.claude/**)` | 전역 Claude 설정 읽기 | 필수 (macOS) |
| `Read(//c/**)` | C 드라이브 전체 읽기 | 선택 (편의성) |

---

## 🛡️ 보안 주의사항

### ✅ DO (해야 할 것)
- `settings.json`에 공통 권한만 추가
- `settings.local.json`에 개인별 경로 추가
- Git 커밋 전 `settings.json` 검토

### ❌ DON'T (하지 말아야 할 것)
- `settings.json`에 개인 경로 추가
- `settings.local.json`을 Git에 커밋
- 민감한 정보 (API 키 등)를 설정 파일에 저장

---

## 📝 트러블슈팅

### 1. "Permission denied" 오류
**원인**: `settings.local.json` 미생성 또는 경로 오류

**해결**:
```bash
# 파일 존재 확인
ls .claude/settings.local.json

# 없으면 생성 (위의 "새 PC에서 설정하기" 참조)
```

### 2. 권한 변경이 적용되지 않음
**해결**: Claude Code 재시작

### 3. Git에 settings.local.json이 추가되려고 함
**원인**: `.gitignore` 미적용

**해결**:
```bash
# .gitignore 확인
cat .gitignore | grep "settings.local.json"

# 이미 추가된 경우 제거
git rm --cached .claude/settings.local.json
```

---

## 🔗 관련 문서

- [`docs/dev-setup-guide.md`](../docs/dev-setup-guide.md) - 전체 개발 환경 세팅 가이드
- [`docs/git-workflow.md`](../docs/git-workflow.md) - Git 브랜치 전략
- [Claude Code 공식 문서](https://docs.claude.com/en/docs/claude-code)

---

**작성자**: HomeworkHelper Dev Team
**최종 수정**: 2025-10-27
