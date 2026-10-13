# 호스트 SSH 진단과 격리 테스트

[종합 가이드](../WORK_GUIDE.md)의 작업별 문서를 확인한다. 이 문서는 증상 분류와 증거 수집 순서를
소유하며 명령·도구 입력·출력은 [공용 운영 도구](../guides/operations-guide.md)가 소유한다.
DB 보호·백업·복구는 [데이터 안전 정책](../data-safety-policy.md), 로그인·권한·감시는
[Windows 수명주기](../development/windows-host-lifecycle.md)를 따른다.

## 상태를 보존하고 문제 경계를 찾는다

재시작·재빌드·설치 전에 현재 상태를 수집한다. 긴 인라인 진단 프로그램을 다시 작성하지 않는다.

| 사용자 흐름과 증상 | 첫 확인 |
|---|---|
| 호스트가 켜졌을 것으로 예상하지만 클라이언트가 응답 없음 표시 | 저장된 대상·Tailscale 연결·SSH 도달 여부. 무응답만으로 물리 전원 꺼짐을 확정하지 않음 |
| PC는 연결되고 Moonlight도 되지만 앱 기능이 대기/인증 오류 | 로그인·앱/API 준비와 원격 인증을 분리. Moonlight 연결 장애로 확대하지 않음 |
| 앱이 느리거나 DB 기능만 멈춤 | ping과 health, DB 보호 상태, 열린 세션, GUI 로그. HTTP listener만으로 DB 정상 판정하지 않음 |
| 실행/종료 버튼에 권한 오류 | 서비스 실행 계정·사용자 SID·Windows 세션·프로세스 생성 시각·상승 여부·관련 로그 |
| OBS 실행 또는 녹화 연결 실패 | OBS 프로세스와 WebSocket 출력 상태를 각각 확인. DB 손상이나 OBS 설정 복원으로 확대하지 않음 |
| 사이드바 높이·작업 영역 문제 | 요청받았을 때 desktop 관찰. 실제 사용자 세션의 창/이벤트로 판단; SSH의 빈 창 목록만으로 결론 내리지 않음 |

기본 상태는 운영 도구의 inspect, 최근 기능 로그는 logs로 확인한다. GUI 정상 종료는 기존
`--quit-application` IPC를 사용하며 패키지 적용은 설치 명령을 따른다. 조사에서 전원 조작·
강제 종료·설정 재작성·토큰 재발급·운영 DB 손상 재현을 자동으로 수행하지 않는다.

서비스는 Application Event Log를 사용한다. GUI 로그의 위치는 지정 사용자의
`AppData/Roaming/HomeworkHelper/homework_helper_data/gui.log`다. 로그 수집과 자격 증명 조회를
구분한다. 토큰·비밀번호·SSH 개인키·쿠키를 출력·문서·커밋에 포함하지 않는다.

## 설치 패키지의 격리 API 테스트

운영 앱 대신 설치 패키지의 shadow copy에서 기존 API 로직을 시험한다.

```bash
./.venv/bin/python tools/ssh_host_testbench.py \
  --host lsh-desktop --user lsh93
# SSH 연결 없는 절차 확인
./.venv/bin/python tools/ssh_host_testbench.py --dry-run \
  --host lsh-desktop --user lsh93
```

필요하면 기존 SSH 키 경로를 identity 옵션으로 지정한다. testbench는 원격 TEMP 아래에 패키지를
복사하고 실행 파일명을 변경하여 `--testbench-server`로 실행한다. API 포트·mutex·AppData와
APPDATA/LOCALAPPDATA를 격리하고 도구가 시작한 PID만 종료한다. 결과는 ignored
`artifacts/ssh-host-testbench/`에 남기며 기본값으로 원격 시험 폴더를 제거한다.

시험 전 설치본이 `--testbench-server`와 AppData/port/mutex 격리를 지원하는지 확인한다.
이 기능이 없는 과거 패키지에 옵션을 추측하여 실행하지 않는다.

실제 서비스·사용자 토큰·데스크톱·게임·OBS·전원 시험은 이 도구의 PASS 범위가 아니다.
공용 운영 도구의 Windows 검사도 설치 단계의 OS 조작을 모의한 결과와 실제 설치를 구분한다.
macOS 인증 테스트는 별도 preferences/cache와 메모리 token store를 확인하고 운영 Keychain을 사용하지 않는다.

## 증거와 결과 보고

DB/WAL/SHM을 임의 삭제하지 않는다. 손상 DB는 정상 업데이트로 수습하지 않고 복구 계약을 따른다.
DB 백업은 기존 writer의 검증된 스냅샷을 사용한다. 예전 문서의 DB 파일 hot copy나 이미지 이름
일괄 종료를 현재 표준으로 재사용하지 않는다.

관측 시각·사용자 동작·대상 커밋·PID/생성 시각/세션·API 결과·관련 로그·수행 범위를 기록한다.
오류는 `사용자의 동작·조건 → 기대 결과 → 실제 결과 → 영향` 순서로 대화에서 직접 보고하고
확인된 사실·격리 재현·코드 위험·미확인 가설을 구분한다. 사건별 상세 기록은 이슈/PR과 ignored
로그·JSON에 보존한다. 운영 문서에 과거 사건의 복사본과 임시 코드를 쌓지 않는다.
