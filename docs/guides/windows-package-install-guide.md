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
공개 커밋과 깨끗한 Windows checkout을 확인하고 build.py의 release를
그대로 사용한다. 소스가 GitHub에 공개되지 않았거나 대상 커밋이 다르면 적용하지 않는다.

Setup 서명, Portable CRC와 고유 제품 payload를 확인한다. 운영 DB/API 정상 준비, 열린 게임 세션,
OBS 녹화·방송·가상 카메라와 활성 리플레이 버퍼, 프로세스 identity, 로그인 사용자 세션을 확인한다.
미확인·오류·사용 중 상태면 설치 전에 중단한다. 준비 실패로 기존 앱·서비스를 중지하지 않는다.

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
공용 install은 `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /HostUser=lsh93`와 설치 로그 경로로
준비된 Setup을 실행하고 실제 종료 코드를 확인한다. Start-Process 호출 성공을 설치 성공으로 보지 않는다.

설치 뒤 앱·서비스 서명이 Valid이고 해시가 Portable payload와 같은지 확인한다. 파일 일치와
release ID가 설치 버전의 근거다. 지원하지 않는 --version 옵션이나 build.version.json만으로 추정하지 않는다.

## 4. 일반 사용자 앱 시작과 확인

서비스가 Running/LocalSystem이고 지정 사용자 SID·로그인 세션이 같은지 확인한다. 설치 직후 앱을
일반 권한으로 한 번 실행한다. 현재 로그온에서 닫힌 앱을 서비스가 다시 여는 정책을 추가하지 않는다.
SSH의 직접 Start-Process로 GUI를 잘못된 세션/상승 권한에서 실행하지 않는다.

한 번 실행하는 InteractiveToken 작업의 앱 RunLevel은 0, ExecutionTimeLimit은 PT0S,
AllowHardTerminate는 false다. 트리거를 만들지 않고 실행 후 등록을 제거한다. 앱을 종료하는 동작이 아니다.
OBS 시작은 기존 제품 트리거가 소유하며 운영 도구가 별도 OBS 자동 시작 작업을 추가하지 않는다.

앱/API SID·세션·elevated=false, DB/API 정상 준비, OBS 실행과 연결, 감시 시작 점검·주기 로그를
구분하여 확인한다. 안전한 사용자 설정과 스크린샷·녹화 경로를 대조한다. OBS 프로필·인코더를 복원하지 않는다.
실제 화면·녹화·다음 로그온 성공을 로그/API 결과로 확대하지 않는다.

## 실패와 보고

준비·백업·정상 종료 실패는 적용 전에 중단한다. Setup 실패는 종료 코드와 설치 로그, 서비스·파일
상태를 확인한다. 파일 서명/payload 불일치에서는 앱 시작 전에 중단한다. 권한·OBS·서비스 오류를
DB 손상으로 표시하지 않으며 UTF-8 디코딩 오류도 치환하지 않는다. 재시도·강제 종료는 자동 선택하지 않는다.

실제 release ID, 백업·설치 결과, 서비스/앱/OBS 권한과 API/로그 확인 범위, 미검증 사용자 항목을
대화에서 직접 보고한다. 자세한 오류 보고 형식은 AGENTS.md를 따른다.
