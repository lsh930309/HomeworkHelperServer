# 빌드 가이드

`build.py`는 Windows host와 macOS remote client를 같은 흐름으로 빌드하는 단일 진입점이다.

- Windows: `windows-host` — PyInstaller onedir, Portable ZIP, Inno Setup installer
- macOS: `macos-client` — Swift release build, `.app` bundle, `.pkg` installer

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

## Windows 인스톨러 종료 정책

인스톨러는 업데이트 전 `homework_helper.exe`만 종료 대상으로 삼는다.

1. 먼저 강제 종료 없이 `taskkill /IM homework_helper.exe`로 정상 종료를 요청한다.
2. 일정 시간 후에도 남아 있으면 사용자 확인을 받아 `taskkill /F /IM homework_helper.exe`를 fallback으로 사용한다.
3. OBS(`obs.exe`, `obs64.exe`)는 종료하지 않는다.

## 검증

빌드 로직 변경 후 최소 검증:

```bash
./.venv/bin/python -m py_compile build.py
./.venv/bin/python -m pytest tests/test_build_release.py -q
```
