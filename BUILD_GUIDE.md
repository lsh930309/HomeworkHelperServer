# 빌드 가이드

## 📦 자동 빌드 스크립트 사용법

### 1. 사전 준비

PyInstaller 설치:
```bash
pip install pyinstaller
```

### 2. 빌드 실행

프로젝트 루트에서 다음 명령 실행:
```bash
python build.py
```

### 3. 빌드 프로세스

스크립트는 다음 단계를 자동으로 수행합니다:

```
1. [준비 단계]
   - release/ 폴더 생성 (없으면)
   - 기존 homework_helper.exe 백업 (타임스탬프로 자동 이름 변경)

2. [빌드 산출물 정리]
   - build/ 폴더 삭제 (이전 빌드 캐시)
   - dist/ 폴더 삭제 (이전 산출물)

3. [PyInstaller 빌드]
   - 단일 실행파일(.exe) 생성
   - 리소스 파일 포함 (font/, img/)
   - 필요한 모듈 자동 포함

4. [최종 파일 복사]
   - dist/homework_helper.exe → release/homework_helper.exe

5. [정리]
   - build/, dist/ 폴더 자동 삭제
```

### 4. 빌드 결과

**최종 실행파일 경로:**
```
release/homework_helper.exe
```

**이전 버전 백업 (예시):**
```
release/homework_helper_25-01-15-143022.exe  (2025-01-15 14:30:22에 생성된 버전)
release/homework_helper_25-01-14-091545.exe  (2025-01-14 09:15:45에 생성된 버전)
```

### 5. 출력 예시

```
============================================================
  숙제 관리자 빌드 스크립트
============================================================
프로젝트 경로: C:\vscode\project\HomeworkHelperServer
빌드 대상: homework_helper.pyw

============================================================
  준비 단계
============================================================
[OK] release 폴더 확인
[OK] 이전 버전 백업: homework_helper_25-01-15-143022.exe

============================================================
  빌드 산출물 정리
============================================================
[OK] 삭제: build/
[OK] 삭제: dist/

============================================================
  PyInstaller 빌드 시작
============================================================
빌드 명령:
python -m PyInstaller --name homework_helper --windowed --onefile ...

... (PyInstaller 출력) ...

[OK] 빌드 성공!

============================================================
  최종 실행파일 복사
============================================================
[OK] 복사 완료: homework_helper.exe -> release/
  파일 크기: 45.32 MB

============================================================
  빌드 산출물 정리
============================================================
[OK] 삭제: build/
[OK] 삭제: dist/

============================================================
  빌드 완료!
============================================================
[OK] 실행파일 경로: C:\vscode\project\HomeworkHelperServer\release\homework_helper.exe
[OK] 이전 버전들: C:\vscode\project\HomeworkHelperServer\release/ 폴더 참조

============================================================
```

## 🔧 빌드 설정 수정

`build.py` 파일 상단의 설정 섹션에서 변경 가능:

```python
# ==================== 설정 ====================
# 빌드 대상
MAIN_SCRIPT = "homework_helper.pyw"
APP_NAME = "homework_helper"

# 포함할 리소스
DATAS = [
    ("font", "font"),
    ("img", "img"),
]

# Hidden imports
HIDDEN_IMPORTS = [
    "uvicorn",
    "fastapi",
    # ... 추가 모듈
]
# ================================================
```

## 📝 주의사항

1. **PyInstaller 버전**: Python 3.13과 호환되는 최신 버전 사용 권장
2. **리소스 파일**: `font/`, `img/` 폴더가 프로젝트 루트에 존재해야 함
3. **의존성**: `requirements.txt`의 모든 패키지가 설치되어 있어야 함
4. **관리자 권한**: 빌드 시 관리자 권한 불필요

## 🐛 문제 해결

### "ModuleNotFoundError" 발생 시
`build.py`의 `HIDDEN_IMPORTS` 리스트에 누락된 모듈 추가

### 빌드는 되지만 실행 안 됨
1. `--onefile` 대신 `--onedir` 모드로 테스트 (build.py 111라인 수정)
2. 콘솔 창 표시: `--windowed` 제거 (디버깅용)

### 파일 크기가 너무 큼
- `--onedir` 모드 사용 고려
- `--exclude-module` 옵션으로 불필요한 모듈 제외

## 📚 참고 자료

- [PyInstaller 공식 문서](https://pyinstaller.org/)
- [PyInstaller 옵션 설명](https://pyinstaller.org/en/stable/usage.html)
