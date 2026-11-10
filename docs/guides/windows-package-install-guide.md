# lsh-desktop Windows 패키지 설치·배포 가이드

이 문서는 빌드가 끝난 Setup 적용 절차의 소유 문서다. 시작 경로는 [종합 가이드](../WORK_GUIDE.md),
빌드·서명·패키징·아카이브는 [빌드 가이드](build-guide.md), 실행 명령은
[공용 운영 도구](operations-guide.md), 로그인·OBS·권한은 [수명주기](../development/windows-host-lifecycle.md),
DB 복구는 [데이터 안전](../data-safety-policy.md)을 따른다.

## 대상과 작업 권한

대상은 Tailscale lsh-desktop, 지정 사용자는 lsh93, 기본 설치 위치는
`C:\Program Files\HomeworkHelper`다. 컴퓨터 이름·사용자 SID·실제 설치 파일을 확인한다.
사용자 승인 범위에서만 조작하며 한국 시각 11:45~13:00의 종료·설치는 별도 예외 승인이 없으면 유예한다.

정상 종료를 우선한다. 공용 설치 명령은 강제 종료·전원 시험·게임 실행·녹화·Moonlight UI 조작을 하지 않는다.
실화면과 다음 로그온 검수는 사용자가 담당한다. 강제 종료가 별도로 승인되었더라도 실제 파일 잠금
소유 PID·경로·생성 시각·게임/녹화 상태를 확인하며 이미지 이름으로 일괄 종료하지 않는다.

## 1. 기존 설치본을 중지하기 전 준비

공용 prepare-source/build/install 명령은 운영 도구 가이드의 사용법을 따른다. 임시 설치 스크립트를
날짜·커밋별로 복제하지 않는다. [고정 작업 저장소](operations-guide.md#lsh-desktop의-고정-작업-저장소)의
공개 커밋과 깨끗한 Windows checkout을 확인하고 build.py의 release를 그대로 사용한다.
맥에서 확정한 호스트 버전이 Windows checkout과 일치하는지 먼저 대조한다. 소스가 GitHub에
공개되지 않았거나 대상 커밋·버전이 다르면 적용을 중단한다.

Setup 서명, Portable CRC와 고유 제품 payload를 확인한다. 운영 DB/API 정상 준비, 열린 게임 세션,
OBS 녹화·방송·가상 카메라와 활성 리플레이 버퍼, 프로세스 identity, 로그인 사용자 세션을 확인한다.
미확인·오류·사용 중 상태면 설치 전에 중단한다. 준비 실패로 기존 앱·서비스를 중지하지 않는다.

사용자가 이전 버전 복귀를 요청한 경우 보관 패키지 선택은
[공용 운영 도구의 archived-release 절차](operations-guide.md#소스-준비빌드설치)를 따른다.
이미 빌드된 원본 Setup과 Portable 쌍을 함께 선택한다. 이후의 정상 백업·종료·Setup·검증 절차는 동일하다.

공용 backup 단계는 기존 `src.data.database.backup_database` writer를 사용하며 읽은 DB 경로가
지정 사용자의 실제 `AppData/Roaming/HomeworkHelper/homework_helper_data/app_data.db`인지 확인한다.
무결성 검사·새 스냅샷 검증·정상 백업이 실패하면 적용하지 않는다. 백업 위치는 지정 사용자의
`AppData/Roaming/HomeworkHelper/backups/app_data.backup.1.db`다. 검사 SQLite 연결은 회전 전에 닫는다.
손상 DB를 업데이트로 복구하지 않는다. 운영 설치 셸에 테스트 AppData/port/mutex 설정을 남기지 않는다.

## 2. 정상 종료와 잠금 해제

OBS가 설치 폴더의 DLL을 사용하면 앱 종료만으로 잠금이 풀리지 않는다. 사용 중인 출력이 없고
해당 사용자·세션·PID·생성 시각이 같은 OBS에만 일회성 InteractiveToken 작업으로 WM_CLOSE를
보내고 종료를 확인한다. 비활성 리플레이 버퍼의 조회 거부를 활성 출력으로 오판하지 않는다.

관리자 SSH의 비대화형 세션은 사용자 GUI 세션과 다르다. CloseMainWindow 실패나 빈 창 목록만으로
앱이 없다고 결론 내리거나 SYSTEM 토큰 복제 경로로 확대하지 않는다. 작업 결과가 없으면 재전송하지
않고 잔여 경로를 보고한다. 작업 등록은 제거하고 완료한 임시 실행 자료만 정리한다.

호스트는 기존 `homework_helper.exe --quit-application`으로 정상 종료를 요청하고 ACK/종료 코드와
GUI/API 종료를 확인한다. 실패·시간 초과·파일 잠금이면 중단하며 자동 강제 종료하지 않는다.

## 3. Setup 적용

Setup이 정상 종료·서비스 전환·기본 설치 위치 적용을 소유한다. 앱/서비스 파일을 수동 교체하지 않는다.
Windows에서 직접 업데이트할 때는 앞의 준비와 정상 종료를 마친 뒤 해당 릴리스의 Setup EXE를 열고
관리자 승인을 한다. 기본 설치 경로에 적용하고, 완료 화면의 앱 실행 선택을 해제한 뒤 4단계에서
앱을 시작한다. 재부팅 안내가 나오면 즉시 재부팅하지 않고 사유·사용 상태·보호 시간을 확인해 별도
승인 범위에서 판단한다.
Windows 터미널에서 Setup을 직접 실행할 때는 `/LOG="<로그 경로>"`로 쓰기 가능한 로그 파일을 지정한다.
로그를 지정하지 않고 실패했다면 오류 창의 메시지와 당시 설치 파일·서비스·앱 상태를 보존한다.
공용 install은 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /HostUser=lsh93`와 설치 로그 경로로
준비된 Setup을 실행하고 실제 종료 코드를 확인한다. Start-Process 호출 성공을 설치 성공으로 보지 않는다.

설치 뒤 앱·서비스 서명이 Valid이고 해시가 Portable payload와 같은지 확인한다. 파일 일치와
release ID가 설치 버전의 근거다. 지원하지 않는 --version 옵션이나 build.version.json만으로 추정하지 않는다.

## 4. 일반 사용자 앱 시작과 확인

서비스가 Running/LocalSystem이고 지정 사용자 SID·로그인 세션이 같은지 확인한다. 설치된 앱이 그
세션에서 일반 권한으로 정상 동작 중이면 유지한다. 앱이 없으면 지정 사용자의 Windows 데스크톱에서
시작 메뉴의 HomeworkHelper를 일반 권한으로 한 번 실행한다. 관리자 권한으로 실행할 대상은 Setup이다.

원격 자동화에서는 [공용 설치 스크립트](../../tools/windows_host_operations.ps1)의 내부 `Start-UserApp`과
같은 InteractiveToken 경계를 사용한다. 일회성 작업의 앱 RunLevel은 0, ExecutionTimeLimit은 PT0S,
AllowHardTerminate는 false다. 트리거를 만들지 않고 실행 후 등록을 제거한다. SSH의 직접 Start-Process로
GUI를 시작하거나 현재 로그온에서 닫힌 앱을 서비스가 다시 여는 정책을 추가하지 않는다.
OBS 시작은 기존 제품 트리거가 소유하며 운영 도구가 별도 OBS 자동 시작 작업을 추가하지 않는다.

앱·서비스 설치 파일의 서명과 Portable 일치로 릴리스 ID를 확인하고, 실제 프로세스의 경로와 시작
시각으로 교체한 설치 파일이 실행 중인지 확인한다. 앱/API는 지정 사용자 SID·세션과 `elevated=false`,
권한 서비스는 Running/LocalSystem이어야 한다. API `ping`과 `health`, `db_ready=true`와 DB 접근 모드
`normal`을 확인하고 안전한 사용자 설정과 스크린샷·녹화 경로를 설치 전과 대조한다. OBS 실행·연결과
감시 로그는 별도로 확인한다.
OBS 프로필·인코더를 복원하지 않는다. 실제 화면·녹화·다음 로그온은 사용자가 별도로 확인한다.

## Windows에서 제거할 때 앱 데이터 선택

Windows의 앱 제거를 확인하면 `앱 데이터와 백업도 삭제` 선택지가 표시된다. 기본은 미선택이며
일반 제거, 무인 제거, Setup 업데이트는 앱 데이터와 백업을 보존한다. 선택하고 계속하면
설치 소유 Windows 사용자의 로컬 `%APPDATA%\HomeworkHelper` 아래 게임 기록, 설정, 백업을
삭제한다. 삭제한 데이터는 복구할 수 없다. 스크린샷·녹화는 [호스트 앱 데이터 폴더 밖에 저장한다](../development/windows-host-lifecycle.md#obs-연동-설정의-권위와-사용자-흐름).
이전 버전에서 앱 데이터 폴더에 저장한 이미지·녹화 파일이 발견되면 앱만 제거하고 앱 데이터와 백업은
보존한다. 이 경우 원본 캡처를 별도 폴더로 옮겨 둔 뒤에만 데이터 정리를 다시 시도한다.

제거 프로그램을 실행한 계정과 설치 소유 SID가 일치하고 Windows 사용자 프로필, Roaming
폴더와 `APPDATA`가 같은 로컬 경로를 가리킬 때만 선택할 수 있다. 실행 중인 설치본은 기존
정상 종료 명령으로 종료하고, 권한 서비스와 이전 자동 실행 항목을 정리한 뒤 데이터를 지운다.
사용자 레지스트리 하이브가 로드되지 않아 이전 Run 값을 확인할 수 없으면 로그에 그 범위를 남긴다.
경로가 링크나 리디렉션을 사용하거나 앱 종료, Game Bar 설정 복원 또는 파일 잠금 상태를
확인할 수 없거나 이전 자동 실행 정리가 확인되지 않으면 보존한다. 삭제 도중 파일 정리가 중단되면 완료로 표시하지 않고 잔여 파일
확인을 안내한다. 데이터를 삭제한 뒤 재설치하면 저장된 BGM 선택이 없어 기본 OFF로 시작한다.

## 실패와 보고

준비·백업·정상 종료 실패는 적용 전에 중단한다. Setup이 실패하면 종료 코드·설치 로그와
[공용 도구의 `inspect`](operations-guide.md#읽기-전용-운영-상태-수집)로 현재 설치 파일·서비스·앱·API를
확인한다. 파일 교체 뒤 후처리가 실패했다면 아래 조건을 모두 충족할 때만 새 설치본의 운영을 복구한다.

1. 설치를 시도한 정확한 릴리스의 Portable ZIP이 CRC 검사를 통과하고, 그 안의 고유한 앱·서비스 EXE의
   SHA-256이 현재 설치된 두 EXE와 각각 일치한다. 두 설치 파일의 Authenticode 상태는 모두 `Valid`다.
   Portable 비교는 [기존 payload 검사](../../tools/windows_host_probe.py)를 사용한다.
2. [제품의 `validate_protected_install`](../../src/host_service/windows_backend.py) 검사가 통과한다.
   서비스 EXE뿐 아니라 `_internal`을 포함한 설치 트리와 상위 경로의 ACL·재분석 지점도 검사한다.
3. 기존 `HomeworkHelperPrivilege`의 `ImagePath`가 기본 위치의 서비스 EXE를 가리키고,
   실행 계정은 `LocalSystem`, 시작 유형은 자동이다. `read_owner_sid`로 읽은 설치 사용자 SID와 지정
   사용자가 일치하고 그 사용자의 로그인 세션은 하나다. 진행 중인 게임·OBS 출력과 프로세스 상태도 확인한다.

불일치·중복·미확인 항목이 있거나 사용 중인 게임·OBS 출력이 있으면 중단한다. 서비스가 `Stopped`이면
관리자 PowerShell에서 `Start-Service -Name HomeworkHelperPrivilege`를 한 번 실행한다. Running과 실제
PID를 확인한 뒤 서비스 EXE의 `--control status`에서 사용자와 단일 세션을 다시 확인한다. 서비스가 이미
실행 중이면 유지하고, 앱 실행 및 검증은 [4단계](#4-일반-사용자-앱-시작과-확인)를 따른다.

이 경로에서 서비스를 다시 등록하거나 설치 파일을 수동 교체하지 않는다. Setup을 자동 재시도하거나
프로세스를 강제 종료하지 않는다. 보관 릴리스로 복귀할 때도 기존 공용 설치의 정상 API/DB 사전 검사를
따른다. 권한·OBS·서비스 오류를 DB 손상으로 표시하지 않으며 UTF-8 디코딩 오류도 치환하지 않는다.

Setup 종료와 후처리의 성공 여부, 확인된 릴리스 ID와 실행 중인 서비스·앱의 운영 복구 여부를 각각 기록한다.
파일 교체 뒤 운영을 복구한 경우에도 Setup 실패와 남은 후처리 확인 항목을 남긴다. 예전 자동 시작 예약 작업·
Startup 바로가기·Run 값은 존재 여부를 확인한다. 백업·API/DB·설정·OBS·로그 확인 결과와 사용자 실화면 검수
여부를 구분해 대화에서 직접 보고한다. 자세한 오류 보고 형식은 AGENTS.md를 따른다.
