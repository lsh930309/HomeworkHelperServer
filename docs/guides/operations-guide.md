# 공용 운영 도구 가이드

[종합 가이드](../WORK_GUIDE.md)에서 작업과 소유 문서를 선택한 뒤 이 목록을 사용한다.
작업 권한·격리·직접 오류 보고·실화면 검수·중복 검증 제한은 [AGENTS.md](../../AGENTS.md)를 따른다.

## 도구와 책임

| 도구 | 책임과 실행 경계 |
|---|---|
| `tools/host_operations.py` | SSH로 읽기 전용 상태 수집, 공개 소스 준비, Windows 빌드·설치, 격리 운영 도구 검사, 요청받은 데스크톱 관찰 |
| `tools/windows_host_operations.ps1` | 고정 Windows 절차. 임의 PowerShell 명령을 사용자 입력으로 받지 않음 |
| `tools/windows_host_probe.py` | 읽기 전용 DB·API·프로세스/토큰·OBS 상태·payload 조회. 명시적 backup만 기존 writer, build만 `build.py` 호출 |
| `tools/windows_session_probe.py` | 일회성 InteractiveToken에서 비활성 데스크톱 관찰 또는 설치에 필요한 OBS 정상 종료. SYSTEM 토큰 복제·강제 종료 없음 |
| `tools/ssh_host_testbench.py` | 설치 패키지 shadow copy의 격리 API 시험. 운영 설치·서비스·전원·게임 시험에 사용하지 않음 |
| `tools/verify_remote_controller.py`, `tools/smoke_*.py` | 기존 원격 계약 자동 검증. 변경 범위에 필요한 검사만 선택 |
| `tools/diagnose_button.py` | 명시적으로 요청된 Windows 입력 이벤트 조사. 일반 진단에서 자동 실행하지 않음 |
| `tools/validate_commit_message.py` | 한국어 계층형 메시지 검사 |
| `build.py` | 각 OS의 전체 빌드·서명·패키징·버전·아카이브·정리. 운영 도구는 이 진입점을 호출할 뿐임 |

## 공통 입력과 결과

`host_operations.py --help`로 실제 옵션을 확인한다. `--host`, `--repo`는 필수이며 `--user`,
`--identity`, `--ssh-port`로 기존 SSH 인증을 사용한다. Windows 빌드 checkout에는 기존 `.venv`가
필요하다. `--computer`와 `--owner` 기본값은 `LSH_DESKTOP`, `lsh93`이고 실제 컴퓨터·SID와 대조한다.
설치 위치는 권장 기본 `C:\Program Files\HomeworkHelper`만 지원한다.

아래 `<Windows 작업 checkout>`에는 실제 빌드용 절대 경로를 넣는다. 설치 폴더를 지정하지 않는다.
날짜별 소스 사본을 새로 만들지 않고 확인된 작업 checkout을 재사용한다.

```bash
./.venv/bin/python tools/host_operations.py inspect \
  --host lsh-desktop --user lsh93 --repo '<Windows 작업 checkout>'
```

각 실행은 `artifacts/host-operations/<UTC 시각-실행 ID>/`에 `result.json`, `stdout.log`, `stderr.log`를
남긴다. stdout에 명령·결과·보고서 경로를 출력하고 실패는 종료 코드 1이다. 상세 로그를 재사용하고
같은 정보를 여러 SSH 호출로 반복 수집하지 않는다. 실패를 성공으로 숨기지 않는다.
결과 파일은 실행 증거이며 제품 상태나 배포 권위가 아니다.
고정 진단·검증 소스는 무손실 압축하여 SSH 입력으로 전달한다. 임시 코드를 다시 생성하지 않으며
제품 패키지의 복사·재포장과는 별개의 소스 전달이다. 통신 시간 초과도 실패 보고서에 남긴다.

## 읽기 전용 운영 상태 수집

`inspect`는 source HEAD/branch/dirty, 빌드 버전, 설치 실행파일 해시, PID·경로·생성 시각·SID·세션·
상승 여부, 열린 게임 세션, 안전한 설정 항목, OBS 출력·설정 파일 해시, `ping`·`health`를 수집한다.
DB는 `mode=ro`로 열고 설정·인증 정보를 변경하지 않는다. 앱의 DB 초기화 모듈을 import하지 않는다.
OBS 비밀번호는 기존 reader로 연결할 때만 메모리에서 사용하고 결과에는 포함하지 않는다.
녹화·장면·인코더·OBS 설정을 쓰는 요청도 보내지 않는다.

API가 꺼져 있거나 DB가 손상되면 각각의 관측 결과로 반환한다. 수집 성공이 앱 준비 성공을 뜻하지 않는다.
설치 커밋은 파일 해시와 해당 패키지 payload 일치로 확인한다. checkout의 버전만으로 설치 버전을 확정하지 않는다.
추가 GUI 로그는 다음 명령으로 최근 1 MiB 안에서 필요한 행만 읽는다. 기존 제품의 redactor를
재사용하며 UTF-8 오류를 치환하지 않는다. 상태 보존 전에 재시작하지 않는다.

```bash
./.venv/bin/python tools/host_operations.py logs \
  --host lsh-desktop --user lsh93 --repo '<Windows 작업 checkout>' --log-lines 80 --contains 'process_scan'
```

inspect 결과에는 로컬 HEAD·실제 공개 브랜치 HEAD와 Windows source를 구분한다. 서비스 실행
계정·시작 모드도 확인한다. 서비스 오류는 Windows Application Event Log에 기록되며 별도의
service.log가 있다고 추측하지 않는다.
문자열 필터는 과거 오류도 찾을 수 있다. 반환된 로그 시각을 현재 상태와 구분하고 최근 상태는
해당 날짜를 contains로 지정하거나 현재 실행 시각 이후의 행에서 확인한다.

## 소스 준비·빌드·설치

먼저 [빌드](build-guide.md)와 [Windows 설치](windows-package-install-guide.md) 가이드를 읽는다.
배포가 승인된 작업에서 관련 검증·커밋·해당 브랜치 푸시 후 순서대로 호출한다.

```bash
./.venv/bin/python tools/host_operations.py prepare-source \
  --host lsh-desktop --user lsh93 --repo '<Windows 작업 checkout>'
./.venv/bin/python tools/host_operations.py build \
  --host lsh-desktop --user lsh93 --repo '<Windows 작업 checkout>'
./.venv/bin/python tools/host_operations.py install \
  --host lsh-desktop --user lsh93 --repo '<Windows 작업 checkout>'
```

로컬의 깨끗한 브랜치 HEAD와 실제 `origin` 브랜치의 공개 HEAD가 같아야 한다. `prepare-source`는
Windows에서 같은 브랜치를 fetch하고 정확한 커밋으로 이동한다. 기존 변경을 덮어쓰지 않는다.
자동 push나 Git bundle 예외는 선택하지 않는다. build/install도 공개 소스·Windows HEAD 일치를 확인한다.
`--commit`은 현재 HEAD를 명시할 때 사용하며 다른 커밋을 조용히 배포하지 않는다.

build는 Windows의 `build.py --no-gui --no-prune-archives`를 호출한다. `--bump`는 기존 옵션을 전달한다.
기존 설치본의 유효한 서명 인증서·개인키를 사용하며 재발급·개인키 복사·수동 서명은 하지 않는다.
Windows checkout의 `artifacts/host-operations-build.log`에 전체 출력을 남긴다.

install은 release·서명/payload·DB·게임·OBS 출력·지정 사용자 세션을 확인하고 기존 writer로 정상
백업한 뒤에만 종료·Setup·일반 사용자 앱 시작을 수행한다. 설치 전후 파일·서명·API·안전한 설정을 대조한다.
설치는 Setup, 자동 시작·OBS 준비는 기존 제품이 소유한다. 녹화·방송·가상 카메라·활성 리플레이·상태
미확인이면 중단한다. 강제 종료·자동 재시도·전원 조작은 포함하지 않는다.

11:45~13:00 한국 시각에는 설치를 유예한다. `--allow-protected-time`은 해당 실행에 사용자의 명시적
예외 승인이 있을 때만 사용한다. 사용 중인 게임·녹화는 이 옵션으로 우회하지 않는다.
세션 작업 결과가 없으면 자동 재실행하지 않고 잔여 임시 경로를 보고한다. 작업 등록은 제거하며 완료된
임시 실행 파일을 정리한다. 파일 잠금 실패는 직접 보고한다.

macOS 패키지는 해당 Mac의 build.py로 준비한다. 설치 관리자 인증은 사용자가 입력한다.
이 Windows 도구는 Mac Keychain·인증·앱 재시작을 조작하지 않는다.
소스 공개·패키지 빌드·설치·API/로그 확인·사용자 실사용 검수 결과를 구분한다.

## 관련 검증 선택

| 변경 경계 | 기존 검사 시작점 |
|---|---|
| 공용 운영·SSH | `tests/test_host_operations.py`, `tests/test_ssh_host_testbench.py` |
| DB 보호·복구·writer | `tests/test_gui_database_recovery.py`, `tests/test_database_access_coordination.py`, `tests/test_data_safety_policy.py` |
| 감시·게임 실행/종료·권한 | `tests/test_managed_process_control.py`, `tests/test_sidebar_process_stop.py`, `tests/test_host_service_transport.py`, `tests/test_host_service_windows_backend.py` |
| OBS 준비·설정 | `tests/test_obs_preparation.py`, `tests/test_pyside_runtime_and_widgets.py` |
| Sidebar·Widgets·모니터 | `tests/test_gui_layout.py`, `tests/test_gui_work_stability.py` |
| 자원·종료 follow-up | `tests/test_resource_followup_lifecycle.py`, `tests/test_game_resource_integrations.py`, `tests/test_resource_manual_gui.py` |
| 빌드·설치 | `tests/test_build_release.py`, `tests/test_installer_tailscale.py`, `tests/test_installer_postinstall_exit.py` |
| macOS 원격 | `tests/test_remote_macos_client_static.py`, 해당 `tools/smoke_macos_*.py`, `swift build --package-path clients/macos` |

표는 선택의 시작점이며 자동 의존성 분석이나 모든 기능의 PASS를 뜻하지 않는다. 실제 변경 경로·
호출자·불변식으로 필요한 검사만 선정한다. macOS 인증 smoke는 임시 preferences/cache와 메모리
TokenStore 주입을 확인한 뒤 실행한다. 운영 Keychain은 fixture로 사용하지 않는다.

공용 도구의 Windows 고유 구문·단계 중단 검증:

```bash
./.venv/bin/python tools/host_operations.py verify \
  --host lsh-desktop --user lsh93 --repo '<Windows 작업 checkout>'
```

고정 도구·관련 테스트만 Windows 임시 폴더에 전달한다. AppData를 격리하고 실제 Windows PowerShell에서
OS 조작을 모의한 설치 흐름을 검사한다. 운영 앱·DB·서비스·작업·OBS는 변경하지 않는다. 테스트 폴더는 제거한다.
실제 설치/UAC/다음 로그온/녹화 성공을 증명하는 검사가 아니다. 설치 패키지의 API 시험은 기존
ssh_host_testbench.py를 사용하며 자세한 격리는 SSH 진단 문서가 소유한다.

## 사용자 세션·작업 표시줄 관찰

요청받은 창 문제에서만 desktop을 사용한다. duration 0은 한 번의 스냅샷이고 최대 120초 관측할 수 있다.
실제 화면·창 geometry, 전경·표시/위치 이벤트와 사이드바를 기록한다. 제품 네이티브 작업 영역 계산을
재사용하며 가짜 SidebarWidget이나 별도 판정식을 만들지 않는다. 키·마우스를 보내거나 창을 활성화하지 않는다.
Moonlight 연결은 요청받았을 때 제품의 Moonlight ON을 사용한다.

```bash
./.venv/bin/python tools/host_operations.py desktop \
  --host lsh-desktop --user lsh93 --repo '<Windows 작업 checkout>' --duration 30
```

로그인 사용자 세션·GUI 의존성이 필요하다. 실패 시 SSH의 빈 창 목록을 실제 창 부재로 해석하지 않는다.
추가 UI 조작·전원 시험으로 확대하지 않는다.
