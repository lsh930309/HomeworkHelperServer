# lsh-desktop Windows 패키지 설치·배포 가이드

이 문서는 빌드가 끝난 Windows Setup을 `lsh-desktop`에 적용하는 운영 절차의 소유 문서다.
빌드·서명·패키징·아카이브는 [빌드 가이드](build-guide.md), 서비스·로그온·OBS의 제품 동작은
[Windows 호스트 계약](../development/windows-host-lifecycle.md), DB 복구는
[데이터 안전 정책](../data-safety-policy.md)을 따른다. 문서는 현재 저장소에서 관리한다.

## 작업 경계와 호스트 확인

- 대상은 Tailscale의 `lsh-desktop`, 지정 사용자는 `lsh93`이다. SSH 접속 대상·Windows 컴퓨터 이름·
  설치 위치를 확인한 뒤 조작한다. 설치 위치는 `C:\Program Files\HomeworkHelper`다.
- 사용자에게 받은 호스트 조작 권한 안에서만 작업한다. 2026-10-12에 승인된 강제 종료는 한국 시각
  **11:45~13:00 밖**에서만 허용된다. 종료 직전에 현재 한국 시각을 다시 확인한다.
  해당 시간에는 사용자 작업과 충돌할 수 있는 종료·설치를 유예한다. 사용자의 중단 요청은 우선한다.
- 정상 종료를 우선한다. 강제 종료가 필요하면 방해하는 파일의 실제 소유 PID·실행 경로·생성 시각과
  녹화/게임 상태를 확인하고, 승인된 범위의 해당 프로세스만 종료한다. 이미지 이름으로 일괄 종료하지 않는다.
- 설치 검증을 위해 재부팅·로그아웃·전원 시험·게임 실행·녹화·Moonlight 화면 확인을 추가하지 않는다.
  실화면과 다음 실제 로그온 검수는 사용자 요청과 별개로 자동 수행하지 않는다.

## 원격 명령 실행 원칙

Mac에서 Windows 명령을 보낼 때는 기존 `tools/ssh_host_testbench.py`의
`run_remote_powershell`을 사용한다. 짧은 UTF-16LE `-EncodedCommand`가 UTF-8 입력 전체를 한 번 읽어
하나의 프로그램으로 실행하고, 오류를 잡아 종료 코드 1을 반환한다. 긴 명령은 SSH/Windows 명령줄 길이
제한을 넘지 않도록 stdin에 둔다. 출력 수집은 UTF-8 strict다.

`powershell -Command -`에 명령을 줄별로 전달하면 앞선 `throw` 뒤의 설치 명령이 실행될 수 있다.
이 방식과 임의의 셸 문자열 이어붙이기를 사용하지 않는다. 호출자도 반환 코드를 확인하고 실패 시
다음 단계로 넘어가지 않는다. PowerShell 5.1에서는 외부 EXE/Python의 실패가 자동 예외가 되지 않으므로
각 실행 직후 `$LASTEXITCODE`, `Start-Process`의 `ExitCode`, 함수의 성공 반환값을 명시적으로 검사한다.

## 1. 설치 전 준비 — 기존 설치본을 중지하기 전에 완료

1. Windows 작업 checkout의 branch·HEAD·dirty 여부와 준비된 Setup의 release ID를 확인한다.
   `build.py`가 만든 `release/`의 파일을 그대로 사용한다. 후보 사본이나 임의 ZIP을 만들지 않는다.
2. Setup Authenticode가 `Valid`인지 확인한다. Portable ZIP CRC와 제품 payload 검증은 빌드 결과를
   참조한다. 기존에 확보한 증거를 반복 생성하지 않는다.
3. 현재 설치된 앱/API/서비스 버전·PID·사용자·Windows 세션, 열린 게임 세션, OBS 출력 상태와
   설치 폴더 DLL 사용 프로세스를 확인한다. SSH에서 창 핸들이 0이라는 이유로 앱이 없다고 판단하지 않는다.
4. 기존 앱·서비스가 동작하는 동안 준비 검사를 끝낸다. 준비 실패 상태에서 앱·서비스를 중지하지 않는다.
5. 운영 DB를 정상 백업하고 성공 여부와 경로를 확인한다. 백업 성공 전에는 설치하지 않는다.

### DB 백업의 정확한 호출

작업 checkout의 Python 환경에서 실행한다. `%APPDATA%`·`HH_TEST_APPDATA_DIR`·`HH_API_PORT` 등이
운영 대상으로 향하는지 먼저 확인한다. 테스트 환경변수가 설정된 셸을 운영 설치에 재사용하지 않는다.

```python
from pathlib import Path
from src.data.database import db_path, backup_database, validate_database_integrity

expected = Path(r"C:\Users\lsh93\AppData\Roaming\HomeworkHelper\homework_helper_data\app_data.db")
assert Path(db_path) == expected
validate_database_integrity(str(expected))
assert backup_database(), "정상 백업 실패: 설치 중단"
```

실제 상수명은 소문자 `db_path`다. `DATABASE_FILE` 같은 존재하지 않는 이름을 추측하지 않는다.
백업은 `C:\Users\lsh93\AppData\Roaming\HomeworkHelper\backups\app_data.backup.1.db`에 저장된다.
별도의 SQLite 읽기 연결로 백업을 검사했다면 반드시 닫은 뒤 백업 회전을 수행한다. 검사 연결을
열어 둔 채 회전하면 Windows 파일 잠금 오류가 발생한다. 백업 실패를 성공으로 처리하지 않는다.
손상 DB는 정상 업데이트로 수습하지 않고 데이터 안전 정책의 복구 절차로 전환한다.

## 2. 정상 종료와 DLL 잠금 해제

- Setup은 기존 설치본의 `homework_helper.exe --quit-application`으로 정상 종료를 요청한다.
  필요하면 이 고정 명령을 먼저 호출하고 ACK/종료 코드와 GUI·API 종료를 확인한다.
- OBS가 `_internal\VCRUNTIME140.dll` 등 설치 파일을 사용하면 앱 종료만으로 잠금이 해제되지 않는다.
  OBS의 녹화·방송·가상 카메라·리플레이 버퍼를 확인한 뒤 정상 종료한다.
  비활성화된 리플레이 버퍼는 조회 요청이 거부될 수 있으므로 현재 프로필의 활성 설정과 구분한다.
- 관리자 SSH의 비대화형 세션과 사용자 GUI 세션은 다르다. `CloseMainWindow()` 실패나 빈 창 목록은
  해당 세션에서 창을 못 본 결과일 수 있다. 무조건 권한을 더 올리거나 다른 SSH를 만들지 않는다.
- 이번에 검증한 정상 종료 경로는 지정 사용자의 `InteractiveToken`으로 한 번 실행한 유지보수 작업에서
  실제 OBS PID의 주 창에 `WM_CLOSE`를 보내는 방식이다. 녹화 등의 출력이 꺼져 있을 때만 수행하고
  프로세스 종료까지 확인한다. 작업 등록은 `finally`에서 제거한다. 영속 시작 작업·주기 감시는 추가하지 않는다.
- 정상 종료가 불가능하면 승인된 시간·범위에서 정확한 방해 PID만 강제 종료할 수 있다.
  종료 후 DLL 잠금이 풀렸는지 확인한다. 파일 사용 오류에 대해 같은 설치를 맹목적으로 반복하지 않는다.

## 3. Setup 실행과 결과 판정

아래는 원격 명령 프로그램 안에서 사용하는 형태다. `$Setup`과 `$InstallLog`는 확인한 기존
release 파일과 작업 로그 경로로 지정한다. 별도 후보 패키지를 복제하지 않는다.

```powershell
if ((Get-AuthenticodeSignature $Setup).Status -ne 'Valid') {
    throw 'Setup 서명 검증 실패'
}
$installer = Start-Process $Setup -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/HostUser=lsh93',
    ('/LOG=' + $InstallLog)
) -Wait -PassThru
if ($installer.ExitCode -ne 0) {
    throw ('Setup 실패: ' + $installer.ExitCode)
}
```

- Setup이 정상 종료·서비스 전환·기본 설치 위치 적용을 소유한다. 앱/서비스의 파일을 수동 교체하지 않는다.
- `Start-Process` 호출 성공을 설치 성공으로 간주하지 않는다. 프로세스 종료 후 Setup 종료 코드를 읽는다.
- 실패하면 설치 로그에서 실제 실패 단계를 보고한다. 파일 복사 완료를 서비스 적용 성공으로 확대하지 않는다.
- 설치 뒤 앱·서비스의 서명이 `Valid`이며, 파일 해시가 패키지의 제품 실행파일과 일치하는지 확인한다.
  설치 버전의 증거는 패키지 release ID와 설치된 파일의 일치다. 지원하지 않는 `--version` 옵션을 추측해 실행하지 않는다.

## 4. 일반 권한 앱 재실행과 운영 확인

1. `HomeworkHelperPrivilege`가 `LocalSystem/Running`이고 다음 명령이 성공하는지 확인한다.

   ```powershell
   & 'C:\Program Files\HomeworkHelper\homework_helper_service.exe' --control status
   if ($LASTEXITCODE -ne 0) { throw '권한 서비스 상태 확인 실패' }
   ```

2. 기존 로그온에서 사용자가 닫은 앱을 서비스가 다시 열지 않는 정책을 유지한다.
   설치 직후에는 지정 사용자 세션에서 앱을 **일반 권한으로 한 번 실행**한다.
   SSH 셸에서 단순 `Start-Process`로 GUI를 실행하면 다른 세션이나 상승 권한이 될 수 있다.
3. 에이전트 직접 실행 시 Windows 작업 스케줄러의 일회성 `InteractiveToken` 작업을 사용할 수 있다.
   사용자 SID는 서비스의 지정 SID, `LogonType=3`, 앱 실행의 `RunLevel=0`으로 지정한다.
   실행파일과 작업 디렉터리는 기본 설치 위치다. 트리거를 등록하지 않고 한 번 `Run`한 뒤 등록을 제거한다.
   작업 등록 제거와 실행 중인 앱 강제 종료는 다른 동작이다. 기존 로그온/OBS 자동 시작 작업은 만들지 않는다.
4. 새 GUI·API의 사용자/SID·세션과 `elevated=false`, OBS의 지정 사용자·같은 세션·`elevated=true`를
   실제 토큰으로 확인한다. 프로세스 이름이나 부모 PID만으로 권한을 판정하지 않는다.
5. `http://127.0.0.1:8000/api/gui/health`의 DB 상태와 최신 GUI 로그에서 시작 점검·주기 감시·
   OBS 연결 결과를 확인한다. OBS 실행 성공과 WebSocket 연결 성공은 따로 기록한다.
6. 사용자 설정·스크린샷/녹화 경로가 보존됐는지 확인한다. OBS 프로필·장면·인코더는 자동 복원하지 않는다.
   UI/실제 녹화/다음 로그온은 수행한 로그·API 검증과 구분한다.

## 실패 시 중단과 보고

| 확인된 실패 | 즉시 처리 |
|---|---|
| 준비 검사·DB 백업 실패 | 설치 전에 중단. 기존 서비스 유지. 원인과 실제 파일 상태 보고 |
| 정상 종료 불가·DLL 사용 중 | 잠금 소유 프로세스 확인. 승인된 종료 방법·시간만 적용 |
| 사용자 세션 실행 접근 거부 | 앱이 실행됐다고 보고하지 않음. 유지보수용 사용자 세션 경로 확인 |
| Setup 비정상 종료 | 종료 코드·설치 로그·기존 서비스 상태 보고. 자동 반복 금지 |
| 설치 파일 서명/해시 불일치 | 앱 재실행 전에 중단. 실제 설치본·패키지 대조 |
| 서비스 또는 앱/API 준비 실패 | 실패 경계를 직접 보고. DB 손상으로 임의 분류하지 않음 |
| 출력 인코딩 오류 | 성공/실패 판정 중단. 문자 치환으로 숨기지 않음 |

모든 오류는 `사용자의 동작·조건 → 기대 결과 → 실제 결과 → 영향` 순서로 대화에서 직접 보고한다.
최종 보고에는 실제 설치 버전, 백업/설치 결과, 서비스·일반 앱·OBS 권한, 미검증 실사용 항목을 남긴다.
