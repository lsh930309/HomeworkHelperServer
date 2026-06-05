# HomeworkHelper

HomeworkHelper는 Windows 호스트 앱과 macOS 메뉴바 원격 클라이언트로 구성된 개인용 게임/프로세스 보조 도구입니다. 현재 활성 개발 범위는 **Windows host**, **macOS remote client**, **Remote Agent**, **대시보드/데이터 안전성**, **배포 빌드 자동화**입니다.

## 현재 지원 범위

- **Windows host app**: PyQt 기반 메인 GUI, 프로세스/웹 바로가기 관리, 세션 기록, 알림, 사이드바, 스크린샷/OBS 보조 기능.
- **Remote Agent**: 호스트 앱의 FastAPI 서버를 통해 상태 조회, 프로세스 실행/종료, 대시보드 요약, pairing/token 기반 보호 endpoint를 제공합니다.
- **macOS remote client**: 메뉴바 popover 중심의 네이티브 Swift 클라이언트입니다. pairing, host 상태 확인, Moonlight 실행 상태 반영, 원격 quick action을 담당합니다.
- **Dashboard frontend**: `src/api/dashboard/frontend`의 Vite/React 앱을 빌드 시 `build/dashboard-static`으로 생성해 PyInstaller 패키지에 포함합니다.

현재 워크스페이스에는 중단된 실험/완료 문서를 남기지 않습니다. 오래된 roadmap, migration, spike, legacy GUI preview 문서는 활성 계약으로 보지 않습니다.

## 빠른 시작

### Windows host 개발 실행

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python homework_helper.pyw
```

서버만 확인할 때는 GUI 단일 인스턴스 경로를 우회합니다.

```bash
python homework_helper.pyw --server
```

### macOS remote client 개발 실행

```bash
swift build --package-path clients/macos
```

앱 번들 패키징은 Python helper 또는 통합 빌드 스크립트를 사용합니다.

```bash
./.venv/bin/python tools/package_macos_remote_app.py
python build.py --target macos-client
```

## 빌드

단일 진입점은 `build.py`입니다. 현재 OS에 맞는 target을 자동 선택하며, GUI 사용 가능 환경에서는 빌드 시작 전에 version/build 후보를 확인하고 조정할 수 있습니다.

```bash
# 현재 OS 기준 target 자동 선택 + GUI version selector
python build.py

# 콘솔/CI용
python build.py --no-gui

# target 강제 지정
python build.py --target windows-host
python build.py --target macos-client
```

버전 상태는 로컬 `build.version.json`에 저장됩니다. 이 파일은 빌드 성공 후에만 갱신되며, 개인 워크스페이스마다 다를 수 있는 local mutable state입니다.

자세한 내용은 [`docs/guides/build-guide.md`](docs/guides/build-guide.md)를 확인합니다.

## 의존성 기준

- Python host/API/build: [`requirements.txt`](requirements.txt)
- Dashboard frontend: [`src/api/dashboard/frontend/package.json`](src/api/dashboard/frontend/package.json)
- macOS remote client: [`clients/macos/Package.swift`](clients/macos/Package.swift)

패키징 캐시와 산출물은 `.gitignore` 정책을 따릅니다. 실험 후 폐기된 GUI preview 경로나 웹 캐시는 Git에 숨겨 보존하지 않습니다.

## 원격 클라이언트 운영 문서

- [`docs/remote/setup-guide.md`](docs/remote/setup-guide.md): Remote Agent, pairing/token, macOS client, supervisor/power 계약, 검증 절차.
- [`docs/remote/host-ssh-diagnostics-runbook.md`](docs/remote/host-ssh-diagnostics-runbook.md): 실제 호스트 SSH 진단과 안전한 testbench 절차.
- [`docs/data-safety-policy.md`](docs/data-safety-policy.md): 설정/DB write 안전 정책.

## 검증 명령

변경 범위에 따라 필요한 검증만 좁혀 실행하되, 원격/빌드 계약을 건드릴 때는 아래 조합을 우선 사용합니다.

```bash
./.venv/bin/python -m py_compile build.py
./.venv/bin/python -m pytest tests/test_build_release.py tests/test_remote_verifier_contract.py -q
./.venv/bin/python -m pytest tests/test_remote_routes.py tests/test_remote_macos_client_static.py -q
./.venv/bin/python tools/smoke_macos_remote_viewmodel.py
swift build --package-path clients/macos
```

## 프로젝트 구조

```text
homework_helper.pyw                  # Windows host entrypoint
build.py                             # platform-aware release builder
requirements.txt                     # Python dependency surface
src/
  api/                               # FastAPI server, dashboard, remote routes
  core/ data/ gui/ recording/ ...    # host app runtime modules
clients/macos/
                                     # Swift menu-bar remote client
tools/                               # packaging, smoke, diagnostic helpers
tests/                               # static/unit/smoke contract tests
docs/                               # active operational docs only
```

## 문서 관리 원칙

- 완료된 작업 기록, 과거 roadmap, migration checklist, spike 문서는 활성 workspace에 두지 않습니다.
- 에이전트가 현재 구현 계약으로 오해할 수 있는 문서는 삭제하거나 README/운영 문서에 흡수합니다.
- 새 문서는 “현재도 따라야 하는 운영/검증 계약”일 때만 추가합니다.
