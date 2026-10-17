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
| `tools/windows_media_probe.py` | 설치 전 미디어·음량·포커스 검수와 격리된 실제 사이드바 렌더링. 운영 DB는 표시 필드만 읽고 조작은 명시한 시나리오만 수행 |
| `tools/ssh_host_testbench.py` | 설치 패키지 shadow copy의 격리 API 시험. 운영 설치·서비스·전원·게임 시험에 사용하지 않음 |
| `tools/verify_remote_controller.py`, `tools/smoke_*.py` | 기존 원격 계약 자동 검증. 변경 범위에 필요한 검사만 선택 |
| `tools/diagnose_button.py` | 명시적으로 요청된 Windows 입력 이벤트 조사. 일반 진단에서 자동 실행하지 않음 |
| `tools/validate_commit_message.py` | 한국어 계층형 메시지 검사 |
| `tools/repository_audit.py` | 전체 checkout의 실제 파일 load 타임테이블과 소스 구조 수집. 삭제·제품 실행·비밀 값 출력 없음 |
| `build.py` | 각 OS의 전체 빌드·서명·패키징·버전·아카이브·정리. 운영 도구는 이 진입점을 호출할 뿐임 |

## 저장소 전체 감사와 작업 자료 정리

전체 감사는 Git 추적 목록에 한정하지 않는다. 다음 도구는 실행 시작 전에 checkout의 모든 파일과
링크를 목록화하고 각 파일의 실제 읽기 시작·완료 시각, 읽은 크기와 결과를 CSV에 기록한다.
이번 실행이 생성하는 보고서 디렉터리는 목록에서 제외해 자기 로그를 무한히 다시 읽지 않는다.
같은 보고서 디렉터리를 덮어쓰지 않으며 파일 삭제·앱 실행·Keychain 조작은 수행하지 않는다.

```bash
./.venv/bin/python tools/repository_audit.py \
  --output artifacts/repository-audit/<새 실행 이름>
```

`file-load-timetable.csv`는 실제 읽기 근거다. 같은 load 기록을 여러 형식으로 중복 보관하지 않는다.
`source-boundaries.json`은
Python을 실행하지 않고 import·함수·쓰기/실행 호출 경계를 추출한다. 소스 구조 추출과 파일 load는
사람이 제품 동작을 리뷰했다는 증거가 아니다. 파일별 소유권·사용처·정리 판단과 그 근거를 별도
검토 결과로 기록하고 미검토 항목을 PASS로 바꾸지 않는다. 기존 파일의 과거 load 시각을 소급 작성하지 않는다.

| 자료 | 확인할 근거와 처리 |
|---|---|
| 제품 소스·소유 문서·공용 도구·테스트·리소스 | 호출·문서 참조·실행 책임을 확인한다. 반복 절차는 기존 경계에 편입하고 임시 복사본을 정리한다. |
| `artifacts/`의 모든 자료 | 확장자에 상관없이 내용을 확인한다. 현재 PR·미해결 조사에 필요한 최소 근거를 선별한다. 완료된 조사 이미지 사본·해제 패키지·중복/빈 출력·과거 중간 자료는 정리 대상이다. |
| 의존성·빌드 캐시 | 선언 파일과 실제 빌드 사용처를 확인한다. 정상 `.venv`·대시보드 의존성·Swift 캐시는 유지한다. 폐기된 실험의 독립 의존성 사본을 정상 의존성과 구분한다. |
| 토큰·운영 데이터·서명 정보·Git·정식 릴리스 | 내용 값을 보고서에 노출하지 않고 보존한다. 프로젝트 정리로 운영 데이터나 build.py의 릴리스 보관을 대신 관리하지 않는다. |

파일별 검토·삭제 목록에는 경로·용도·판단 근거·실행 결과를 남긴다. 삭제할 근거 안에만 재사용
절차가 있으면 먼저 편입한다. 심볼릭 링크는 링크 자체만 기록하며 checkout 밖의 대상을 따라가지 않는다.
Git IPC 소켓 등 일반 파일이 아닌 항목은 열지 않았다는 결과를 명시한다. 읽기 실패·실행 중 변경과
목록 누락은 완료로 숨기지 않는다. 관련 검사는 `tests/test_repository_audit.py`를 사용한다.
Git 추적 파일이 디스크에 없더라도 감사 대상에 포함하며, 실제 읽기 실패와 종료 코드 1로 알린다.

파일별 처리 판단은 CSV의 `disposition` 열이 소유한다. 처리 변경 뒤에도 같은 표에서 현재 건수를
즉시 계산하며 수동으로 갱신하는 별도 집계 JSON을 유지하지 않는다.

```bash
./.venv/bin/python tools/repository_audit.py --summarize-dispositions '<파일별 처리표.csv>'
```

이 명령은 표를 읽어 집계만 출력하며 파일을 생성·수정하지 않는다. 완료된 일회성 보고 자료는
관련 판단을 공용 도구·계약과 이슈/PR에 반영한 뒤 사용자 요청과 보존 필요에 따라 정리한다.

## 공통 입력과 결과

`host_operations.py --help`로 실제 옵션을 확인한다. `--host`는 필수이며 `--user`,
`--identity`, `--ssh-port`로 기존 SSH 인증을 사용한다. Windows 빌드 checkout에는 기존 `.venv`가
필요하다. `--computer`와 `--owner` 기본값은 `LSH_DESKTOP`, `lsh93`이고 실제 컴퓨터·SID와 대조한다.
설치 위치는 권장 기본 `C:\Program Files\HomeworkHelper`만 지원한다.

### SSH 이름과 실제 연결 주소

`--host`에는 명시적 IP, Tailscale의 장치 이름·전체 DNS 이름 또는 일반 전체 도메인을 전달한다. Tailscale 이름 입력은
공용 SSH 실행 경계가 기존 `src/core/tailscale.py`의 최신 peer 목록에서 정확히 한 장치를
찾고, 그 장치의 현재 IPv4(없으면 IPv6)를 OpenSSH의 `HostName`에 지정한다. OS DNS를 먼저
시도하지 않으며 개인 IP를 코드·설정에 고정하지 않는다. 원래 SSH 대상·사용자·키·포트와
host key 검증은 유지한다. host-operations의 모든 명령과 SSH testbench가 같은 경계를 사용한다.
`--user`를 생략한 기존 `user@host` 입력도 지원한다. `.ts.net` 밖의 일반 전체 도메인 이름은
기존 SSH의 DNS 경로를 유지한다. 짧은 장치 이름과 MagicDNS 이름은 Tailscale 대상이다.

이름 비교는 장치 이름, 전체 DNS 이름, DNS 이름의 첫 부분에 대한 대소문자 무시 완전 일치다.
일치 대상 없음·복수 일치·주소 없음·Tailscale 미준비는 SSH 실행 전에 명확히 실패한다.
온라인인 다른 PC로 전환하지 않고 offline 표시만으로 다른 주소를 선택하거나 Wake하지 않는다.
명시적 IP는 Tailscale 조회 없이 그대로 사용하며, dry-run은 실제 주소 조회·연결을 하지 않는다.
실행 실패·인증 실패·시간 초과 뒤 다른 주소로 자동 재전송하지 않는다.

MagicDNS가 tailnet에서 켜져 있어도 Mac의 `Use Tailscale DNS settings`가 꺼져 있으면 OS의
이름 조회는 일반 네트워크 DNS로 전달되어 짧은 이름과 전체 Tailscale 이름이 모두 실패할 수 있다.
이는 IP 연결이나 Tailscale 내부 DNS의 실패와 구분한다
([Tailscale의 장치별 DNS 설정](https://tailscale.com/docs/features/magicdns#disabling-magicdns)).
공용 도구는 이 OS 설정과 독립적으로 주소를 조회한다. 회사 DNS·Tailscale 설정·`/etc/hosts`를
자동 변경하지 않는다. DNS와 내부 peer 조회의 구분은 [SSH 진단 가이드](../remote/host-ssh-diagnostics-runbook.md#dns와-tailscale-주소-조회를-구분한다)를 따른다.

### lsh-desktop의 고정 작업 저장소

제품 소스 준비·빌드·설치는 기존 `C:\VSCode\Projects\HomeworkHelperServer` 한 곳을 사용한다.
`host_operations.py`의 `WINDOWS_REPO`가 실행 경로를 소유하며 `--repo` 선택 옵션은 제공하지 않는다.
다른 checkout·Temp 저장소를 만들거나 대체 경로로 자동 전환하지 않는다. 기존 저장소 또는 `.venv`가
없으면 중단하여 원인을 확인한다. 설치 폴더 `C:\Program Files\HomeworkHelper`와 구분한다.

`build.py`는 이 저장소에서 실행하며 로컬 `build.version.json`, 최종 `release/`와
`release/archives/`를 계속 사용한다. 작업 저장소를 이전할 때는 기존 변경·로컬 Git 이력·버전·패키지·
사용자 설정·서명을 먼저 확인하고 보존한다. 같은 상대 경로의 파일은 내용이 같을 때만 합치며 다른
내용을 조용히 덮어쓰지 않는다. 이전 자료의 검증 완료 후에만 폐기 저장소를 제거한다.

```bash
./.venv/bin/python tools/host_operations.py inspect \
  --host lsh-desktop --user lsh93
```

각 실행은 `artifacts/host-operations/<UTC 시각-실행 ID>/`에 `result.json`, `stdout.log`, `stderr.log`를
남긴다. stdout에 명령·결과·보고서 경로를 출력하고 실패는 종료 코드 1이다. 상세 로그를 재사용하고
같은 정보를 여러 SSH 호출로 반복 수집하지 않는다. 실패를 성공으로 숨기지 않는다.
결과 파일은 실행 증거이며 제품 상태나 배포 권위가 아니다.
고정 진단·검증 소스는 무손실 압축하여 SSH 입력으로 전달한다. 임시 코드를 다시 생성하지 않으며
제품 패키지의 복사·재포장과는 별개의 소스 전달이다. 통신 시간 초과도 실패 보고서에 남긴다.
시간 초과 때까지 받은 stdout/stderr는 같은 로그 파일에 원본 바이트로 보존한다. 끝이 잘린 UTF-8을
치환하지 않으며, 실패 판정과 자동 재시도하지 않는 정책을 유지한다.

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
  --host lsh-desktop --user lsh93 --log-lines 80 --contains 'process_scan'
```

inspect 결과에는 로컬 HEAD·실제 공개 브랜치 HEAD와 Windows source를 구분한다. 서비스 실행
계정·시작 모드도 확인한다. 서비스 오류는 Windows Application Event Log에 기록되며 별도의
service.log가 있다고 추측하지 않는다.
문자열 필터는 과거 오류도 찾을 수 있다. 반환된 로그 시각을 현재 상태와 구분하고 최근 상태는
해당 날짜를 contains로 지정하거나 현재 실행 시각 이후의 행에서 확인한다.

## 소스 준비·빌드·설치

### 설치 전 미디어·사이드바 검수

명시적으로 실호스트 검수가 허용되면 공개된 현재 커밋을 `prepare-source`로 준비한 뒤 실행한다.
설치본은 교체하지 않으며 지정 사용자 InteractiveToken에서 일반 권한으로 실행한다.

```bash
./.venv/bin/python tools/host_operations.py media-qa \
  --host lsh-desktop --user lsh93 --scenario observe --prepare-runtime
./.venv/bin/python tools/host_operations.py media-qa \
  --host lsh-desktop --user lsh93 --scenario preview
```

`--prepare-runtime`은 처음 필요한 경우에만 고정 저장소 `.venv`에 `requirements.txt`를 설치한다.
제품 빌드·서명·설치는 수행하지 않는다. pip 전체 출력은 Windows 저장소의
`artifacts/media-qa-requirements.log`에서 확인한다. `observe`는 자동 옵션을 모두 끈 실제
미디어 runtime·전경 창·WASAPI 세션을 관측하고 종료한다. `preview`는 실제 SidebarWidget에
표시 필드만 읽은 fixture를 주입하며 모든 조작을 차단한다. AppData·LocalAppData·앱 상태 경로를
제품 모듈 import 전에 격리하고, 운영 자격 증명과 DB writer를 사용하지 않는다.

결과에는 단계별 native 오류·정리 결과 또는 작업 영역/760/1080 높이의 PNG·DPR·컨트롤 좌표·
스크롤 범위가 포함된다. PNG는 같은 로컬 실행 보고서에 저장한다. 위젯 PNG는 실제 Windows
폰트·레이아웃의 근거이며 DWM이 배경과 합성한 Acrylic 품질의 증거는 아니다.
`audio`는 매우 낮은 소리의 자기 소유 WAV 프로세스로 실제 WASAPI의 전경·배경·사용자 음소거·
0%와 55%를 확인하고 초기 음량을 복원한다. `focus`는 자기 소유 비활성 Qt 창에 한 번 전환한 뒤
실제 foreground PID와 중복 요청 부재를 확인하고 원래 창을 복원한다. 두 fixture는 정상 종료하며
90초 자체 상한을 둔다. 운영 게임 실행·DB 이용 기록을 만들지 않는다.

`prepare-spotify`는 실제 제품의 명시적 준비 요청을 한 번 실행하고 세션 출현을 관측한다.
재생은 요청하지 않는다. `bgm`은 이미 있는 명확한 단일 playing/paused Spotify 세션에서
Play/Pause 전환을 관측한 뒤 원래 재생 상태로 복원한다. 세션 없음·복수·unknown·stopped처럼
복원할 수 없는 조건에서는 실패 사유를 반환하고 임의 재생하지 않는다. 로그인이나 곡 선택은
제품에서 사용자가 준비해야 하며 자격 증명을 도구가 읽거나 대신 입력하지 않는다.
관측·렌더링 성공을 실제 재생·음량·포커스 전환 성공으로 확대하지 않는다. 자동 정책 입력의 합성
검증과 실제 Windows I/O 검증을 각각 기록하며 Firefox의 탭 종료를 추정하지 않는다.
`triggers`는 전경 입력만 고정하고 실제 Spotify·WASAPI·runtime으로 자동 켜기 → 게임 음성 →
사용자 음소거 → 수동 일시정지의 연결을 검증한다. 자동 포커스는 이 시나리오에서 끈다.
관측한 명령·재생 변화와 고정 입력을 구분하고 원래 Spotify 상태와 시험 음량을 복원한다.

먼저 [빌드](build-guide.md)와 [Windows 설치](windows-package-install-guide.md) 가이드를 읽는다.
배포가 승인된 작업에서 관련 검증·커밋·해당 브랜치 푸시 후 순서대로 호출한다.

```bash
./.venv/bin/python tools/host_operations.py prepare-source \
  --host lsh-desktop --user lsh93
./.venv/bin/python tools/host_operations.py build \
  --host lsh-desktop --user lsh93
./.venv/bin/python tools/host_operations.py install \
  --host lsh-desktop --user lsh93
```

로컬의 깨끗한 브랜치 HEAD와 실제 `origin` 브랜치의 공개 HEAD가 같아야 한다. `prepare-source`는
고정 Windows 저장소에서 같은 브랜치를 fetch하고 `FETCH_HEAD`가 대상 커밋과 같은지 확인한 뒤
`checkout --detach <커밋>`으로 이동한다. 단순 pull·merge로 바꾸지 않고 기존 변경을 덮어쓰지 않는다.
자동 push나 Git bundle 예외는 선택하지 않는다. build/install도 공개 소스·Windows HEAD 일치를 확인한다.
`--commit`은 현재 HEAD를 명시할 때 사용하며 다른 커밋을 조용히 배포하지 않는다.
install의 release ID는 Windows의 `build.py` 버전 계산을 그대로 사용한다. 운영 도구가 파일명이나
Git 축약 길이를 따로 계산하지 않으므로 `core.abbrev` 설정이 달라도 같은 패키지를 선택한다.

사용자가 이전 설치본으로 복귀를 요청하면 `install --archived-release <정확한 릴리스 ID>`를 사용한다.
고정 저장소의 `release/archives/windows-host/`에서 같은 ID의 Setup·Portable이 각각 하나여야 하며,
기존 서명·CRC/payload·사용 상태·정상 백업·정상 종료·설치 후 검증을 그대로 수행한다. 이 경로는 이미
생성된 보관 패키지를 설치하므로 현재 소스 HEAD 공개·checkout 변경·재빌드를 요구하지 않는다.
`--commit`과 함께 지정하지 않는다. DB·사용자 설정을 과거 백업으로 복원하거나 로컬 빌드 버전을
낮추지 않으며, 설치 버전은 선택한 Portable의 payload와 실제 설치 파일을 대조해 판정한다.
보호 시간 예외 승인과 게임·녹화 중단 조건은 일반 설치와 같다.

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
  --host lsh-desktop --user lsh93
```

고정 도구·관련 테스트만 Windows 임시 폴더에 전달한다. 이 폴더는 제품 빌드·배포 저장소가 아닌
격리 테스트 fixture이며 제품 패키지를 만들거나 설치하지 않는다. AppData를 격리하고 실제 Windows PowerShell에서
OS 조작을 모의한 설치 흐름을 검사한다. 운영 앱·DB·서비스·작업·OBS는 변경하지 않는다. 테스트 폴더는 제거한다.
실제 설치/UAC/다음 로그온/녹화 성공을 증명하는 검사가 아니다. 설치 패키지의 API 시험은 기존
ssh_host_testbench.py를 사용하며 자세한 격리는 SSH 진단 문서가 소유한다.

## 사용자 세션·작업 표시줄 관찰

요청받은 창 문제에서만 desktop을 사용한다. duration 0은 한 번의 스냅샷이고 최대 120초 관측할 수 있다.
각 창의 실제 위치·표시 여부와 DPI·입력 투명 스타일을 함께 수집하며, 커서 아래의 실제
Windows 창도 기록한다. 클릭 실패를 조사할 때는 클릭이 손잡이에 도달했는지와 사이드바가
화면 안으로 이동했는지를 먼저 구분한다. 이 관찰만으로 Qt 내부 상태나 오류 원인을 확정하지 않는다.
실제 화면·창 geometry, 전경·표시/위치 이벤트와 사이드바를 기록한다. 제품 네이티브 작업 영역 계산을
재사용하며 가짜 SidebarWidget이나 별도 판정식을 만들지 않는다. 키·마우스를 보내거나 창을 활성화하지 않는다.
Moonlight 연결은 요청받았을 때 제품의 Moonlight ON을 사용한다.

```bash
./.venv/bin/python tools/host_operations.py desktop \
  --host lsh-desktop --user lsh93 --duration 30
```

로그인 사용자 세션·GUI 의존성이 필요하다. 실패 시 SSH의 빈 창 목록을 실제 창 부재로 해석하지 않는다.
추가 UI 조작·전원 시험으로 확대하지 않는다.
