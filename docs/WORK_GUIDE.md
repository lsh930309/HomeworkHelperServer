# HomeworkHelper 종합 작업 가이드

README는 앱 소개다. 이 문서는 개발·진단·검증·배포를 시작하는 경로와 문서 소유권을 안내한다.
작업 규칙은 [AGENTS.md](../AGENTS.md), 실행 명령과 공용 도구는
[공용 운영 도구 가이드](guides/operations-guide.md)가 소유한다.

## 작업별 필수 읽기

해당하는 행을 모두 확인한다. 모든 문서와 과거 로그를 매번 전부 읽지 않는다.

| 작업 | 필수 소유 문서 |
|---|---|
| 모든 관련 작업 | 이 가이드, [작업 규칙](../AGENTS.md) |
| 제품 소개·사용자 기능·지원 환경·릴리스 표기 | [README](../README.md), [README 유지관리 규칙](../AGENTS.md#readme-제품-소개-유지관리), 변경한 기능의 소유 문서 |
| 문제 진단·반복 검증·공용 도구 변경 | [운영 도구](guides/operations-guide.md), [SSH 진단](remote/host-ssh-diagnostics-runbook.md) |
| 저장소 전체 감사·임시 자료 정리 | [운영 도구의 저장소 감사](guides/operations-guide.md#저장소-전체-감사와-작업-자료-정리), [작업 규칙](../AGENTS.md) |
| 호스트·클라이언트 소스 준비·빌드·서명·패키지 배포 | [빌드](guides/build-guide.md), [운영 도구](guides/operations-guide.md) |
| lsh-desktop 패키지 설치 | 위 빌드 문서와 [Windows 설치](guides/windows-package-install-guide.md) |
| 로그인·권한·감시·게임 실행/종료·OBS 연동 | [Windows 수명주기](development/windows-host-lifecycle.md) |
| DB·백업·복구·자원 추적·저장 경계 | [데이터 안전](data-safety-policy.md) |
| Windows GUI·사이드바·모니터·작업 영역 | [PySide6 Widgets 계약](development/windows-gui-modernization.md) |
| 원격 인증·연결 모델·Moonlight·클라이언트 | [원격 설정](remote/setup-guide.md), [Windows 수명주기](development/windows-host-lifecycle.md) |
| 커밋·PR | [커밋 메시지](development/commit-message-policy.md), [작업 규칙](../AGENTS.md) |

## 실행 환경과 개발 시작

- Windows 호스트·API: [requirements.txt](../requirements.txt).
- macOS 클라이언트: [Package.swift](../clients/macos/Package.swift).
- 대시보드: [package.json](../src/api/dashboard/frontend/package.json).
- `tools/`: 공용 실행 자산, `tests/`: 사용자 계약 자동 검증.
- `docs/`: 현재 운영·제품 계약, `artifacts/`: Git에 포함하지 않는 실행 증거.
- `release/`와 로컬 `build.version.json`: `build.py`가 관리하는 산출물·버전 상태.

Windows 개발 실행:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe homework_helper.pyw
```

GUI 없는 개발 API 실행은 `homework_helper.pyw --server`다. 운영 앱과 동일한 DB·포트를 사용하는
개발 실행을 격리 테스트로 취급하지 않는다. 실호스트 시험은 운영 도구의 격리 경로를 사용한다.
설치와 권한 기능은 Windows 수명주기·설치 가이드를 따른다.

macOS 개발 빌드는 `swift build --package-path clients/macos`, 패키지 빌드는 해당 Mac의
`python build.py`다. 패키지 절차를 직접 재구성하지 않는다.

## 문서·도구 유지관리

문제의 사용자 흐름을 정의하고 소유 문서와 공용 도구를 찾는다. 확인된 계약 변경은 그 문서만 갱신하고
반복 절차는 도구와 관련 검사에 편입한다. 없는 옵션을 추측하거나 날짜별 임시 스크립트를 표준으로 실행하지 않는다.

한 사실의 정책·명령 사용법·실행 결과를 여러 문서에 복제하지 않는다. 다른 문서는 링크한다.
도구 한계는 운영 가이드에, 장애·해결은 이슈/PR에, 로그·JSON 증거는 `artifacts/`에 남긴다.
편입 완료한 계획·초안·일회성 코드는 제거한다. 데이터·인증 정보·사용 중인 파일·릴리스 패키지는
임시 코드 정리 대상이 아니다.
