# 빌드 가이드

`build.py`는 Windows host와 macOS remote client를 같은 흐름으로 빌드하는 단일 진입점이다.

## 필수 기본 절차

호스트·클라이언트 빌드와 패키지 배포 작업은 먼저 저장소의
[종합 가이드](../WORK_GUIDE.md)의 해당 문서와 이 문서를 읽고 시작한다.
Windows에서는 Windows 저장소 환경에서, macOS에서는 macOS 저장소 환경에서
`python build.py`를 실행한다. 별도 옵션이 필요한 경우에만 아래의 지원 옵션을 사용한다.

`build.py`가 대상 선택, 빌드 환경 준비, 버전 선택, 이전 산출물 보관,
플랫폼 빌드·서명·패키징, 성공한 버전 저장, 결과 안내와 중간 파일 정리를 소유한다.
패키지 산출물 준비는 이 스크립트의 실행 흐름으로 완료한다. 개별 패키징 도구를 직접
이어 호출하거나 스크립트 밖에서 버전·서명·아카이브·배포 묶음을 다시 만들지 않는다.

기본 산출물을 `release/alwayson/<커밋>/` 같은 추가 후보 폴더에 복사하거나,
호스트와 클라이언트의 패키지를 한 환경으로 모으거나, `.app`을 별도 ZIP으로
재포장하지 않는다. 검증 로그·리뷰 기록은 `artifacts/`에 두고 실제 산출물을 참조한다.
사용자가 별도 파일 전달을 명시한 경우에만 그 요청 범위에서 복사한다.

이 문서는 빌드·패키지 배포 절차의 소유 문서다. 다른 문서는 이 문서를 링크한다.

- Windows: `windows-host` — PyInstaller onedir, Portable ZIP, Inno Setup installer
- macOS: `macos-client` — Swift release build, `.app` bundle, `.pkg` installer

최종 배포 파일은 Windows의 Setup EXE·Portable ZIP과 macOS의 PKG다.
macOS `.app`은 PKG 생성에 사용하는 중간 산출물이다.
Windows Setup의 lsh-desktop 적용 절차는 [패키지 설치 가이드](windows-package-install-guide.md)를 따른다.

## 공개 소스와 대상 환경 준비

배포가 승인된 작업은 관련 검증·커밋·작업 브랜치 푸시를 완료한다. 공개 커밋과 Windows 빌드
checkout을 맞추는 명령은 [공용 운영 도구](operations-guide.md#소스-준비빌드설치)를 사용한다.
기존 작업 트리의 변경을 덮어쓰거나, 원격보다 앞선 소스를 임의 Git bundle로 전달하지 않는다.
사용자가 명시한 로컬 배포 예외만 별도로 기록한다.

Windows 제품은 Windows에서, macOS 제품은 Mac에서 빌드한다. `build.py` 실행 전 실제 OS·checkout·
커밋·dirty 여부와 해당 환경의 로컬 버전을 확인한다. 빌드 버전·산출물과 설치 결과는 서로 다른 증거다.
소스 공개, 빌드/서명 성공, 설치, 로그/API 확인, 사용자 검수 범위를 각각 보고한다.

## Windows 개발 환경 준비

Python 3.14와 Python Launcher를 먼저 설치한다. `python build.py`는 프로젝트 `.venv`가 없으면
Python 3.14로 생성하고, 해당 환경에서 `requirements.txt`를 설치·갱신한 뒤 빌드를 이어간다.
가상환경 삭제·재생성을 정상 빌드의 선행 단계로 실행하지 않는다. 기존 환경의 Python 버전이
다르거나 손상됐으면 실제 오류를 먼저 확인하고 수동 환경 정비와 정상 빌드를 구분한다.

## 로컬 버전 상태

`build.version.json`은 Git에 커밋하지 않는 로컬 mutable state다. 각 워크스페이스에서 현재 배포하려는 target별 version/build를 보관한다.

```json
{
  "schema": 1,
  "targets": {
    "windows-host": {"version": "1.2.0", "build": 1},
    "macos-client": {"version": "0.2.0", "build": 1}
  }
}
```

빌드는 시작 시 후보 버전을 만들고, 산출물이 실제로 생성된 경우에만 이 파일을 저장한다. 실패한 빌드는 버전 파일을 갱신하지 않는다.

릴리스 ID 형식:

```text
v{semver}_b{build}_g{git-hash}[_dirty]
```

예시 산출물:

```text
HomeworkHelper_v1.2.0_b2_gabc1234_Setup.exe
HomeworkHelper_v1.2.0_b2_gabc1234_Portable.zip
HomeworkHelperRemote_v0.2.0_b2_gabc1234.pkg
```

## 기본 실행

```bash
# 현재 OS 기준 target 자동 선택, GUI version selector 사용
python build.py

# 콘솔/CI 환경
python build.py --no-gui

# target 강제 지정
python build.py --target windows-host
python build.py --target macos-client
```

GUI 사용 가능 환경에서는 Windows host와 macOS client 모두 같은 version selector를 사용한다. 후보 버전은 `--bump` 결과로 채워지고, 사용자는 방향키로 semver를 조정한 뒤 Enter로 확정한다. Esc는 빌드를 취소한다.

## 버전 증가 정책

```bash
python build.py --bump build   # 기본값: 같은 semver에서 build +1
python build.py --bump patch   # patch +1, build=1
python build.py --bump minor   # minor +1, patch=0, build=1
python build.py --bump major   # major +1, minor=0, patch=0, build=1
python build.py --bump none    # 현재 파일 값을 그대로 사용
```

동일 semver의 build 번호는 자동 계산한다. semver를 올리면 build는 1부터 시작한다.

## Archive 관리

빌드 시작 시 `release/` 루트의 기존 배포 산출물은 아래 구조로 이동한다.

```text
release/archives/{target}/{artifact_type}/{YY-MM-DD}/{artifact}
```

기본 pruning 정책:

- target/type별 최신 10개 보존
- 90일 초과 산출물 삭제

옵션:

```bash
python build.py --archive-keep 20 --archive-days 180
python build.py --no-prune-archives
```

기준 산출물 보존이 필요한 작업은 위의 지원 옵션을 사용한다. 추가 후보 사본을
만들지 않는다. 과거 아카이브 부재의 원인은 삭제 기록 없이 추정하지 않는다.

## Windows 배포용 서명 준비

Windows 배포 빌드 전에는 기존 인증서의 개인키가 현재 사용자의 `My` 인증서 저장소에
있는지 확인하고, 작업 프로세스의 `HH_CERT_THUMBPRINT` 또는 기존 `certs/.thumbprint`로
정확한 인증서를 지정한다. 격리된 소스 checkout에는 무시된 `.thumbprint` 파일이 없을 수
있으므로 이전 빌드 셸의 환경변수를 새 SSH 프로세스가 이어받는다고 가정하지 않는다.
lsh-desktop 업데이트는 현재 설치본의 유효한 서명 인증서를 기준으로 같은 인증서·개인키를
확인한다. 인증서 재발급·개인키 복사·저장소에 fingerprint 고정은 하지 않는다.

인증서 지정 없이 `build.py`가 패키지를 만들고 서명을 생략한 경우는 배포 준비 완료가
아니다. 기존 인증서를 올바르게 지정하고 같은 버전은 `--bump none`을 사용해 `build.py`
전체 절차를 다시 실행한다. 개별 EXE나 ZIP을 수동으로 서명·재포장하지 않는다. 설치 전에는
최종 Setup과 제품 payload의 서명이 `Valid`인지 확인한다.

## macOS 서명 identity

기존 인증서·개인키·신뢰·운영 인증 토큰은 유지한다. Keychain 표시 라벨은 제품·용도와
fingerprint 일부로 구분하고 인증서를 재발급하지 않는다. build.py는 유효한 identity를
정확히 찾은 SHA-1 fingerprint로 codesign을 호출한다. 환경변수 지정도 정확히 검증하며
중복 이름은 임의 선택하지 않는다. 로컬 fingerprint를 저장소에 고정하지 않는다.
외부 배포용 PKG 서명·공증은 별도 범위다.

## 선택적 GitHub Release 게시

`--publish-release`는 기본 비활성화이다. 활성화해도 조건이 맞지 않으면 빌드 실패로 처리하지 않고 게시만 건너뛴다.

필요 조건:

- `gh` CLI 사용 가능
- 작업 트리가 깨끗함
- 현재 릴리스 ID를 포함한 산출물이 존재함

태그 형식:

```text
hh-{target}-v{semver}-b{build}
```

## 검증

빌드 로직 변경 후 최소 검증:

```bash
./.venv/bin/python -m py_compile build.py
./.venv/bin/python -m pytest tests/test_build_release.py -q
```
## Windows 로그인·권한 경계

Windows 패키지는 일반 권한 앱과 headless 권한 서비스를 함께 포함합니다.
설치·사용자 계정·포터블 등록·실기기 검수 범위는
[Windows 호스트 수명주기 계약](../development/windows-host-lifecycle.md)을 따릅니다.
