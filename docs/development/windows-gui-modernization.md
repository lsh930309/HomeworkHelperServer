# Windows GUI 현대화 검증 가이드

## 실행 모드

Windows 호스트의 기본 presentation은 modernized Qt Widgets다. 동일 backend와
수명주기를 사용하는 독립 Qt Quick 후보는 다음 중 하나로 실행한다.

```powershell
$env:HH_UI_RENDERER = 'qml'
python homework_helper.pyw
```

```powershell
python homework_helper.pyw --ui-renderer=qml
```

지원 값은 `widgets`, `qml`뿐이다. QML 로드에 실패하면 안정성을 위해 Widgets로
복귀하며 원인은 GUI 로그에 기록된다. 런타임 manifest와 Windows incident ZIP에는
binding, renderer, variant 식별자가 포함된다.

제품 기본 onedir는 Qt Quick 모듈을 제외해 Widgets 설치 크기를 QML 후보와 분리한다.
QML 후보 설치본은 별도 출력 디렉터리에서 다음과 같이 만든다.

```powershell
$env:HH_INCLUDE_QML = '1'
$env:HH_UI_RENDERER = 'qml'
python -m PyInstaller homework_helper.spec --noconfirm
```

`HH_INCLUDE_QML=1` 없이 만든 기본 설치본에서 QML을 요청하면 Widgets로 복귀한다.
두 설치본의 크기와 실행 성능을 각각 기준선과 비교해야 한다.

## PySide6 빌드 경계

- Python 3.14 및 `PySide6==6.11.1`을 사용하는 깨끗한 가상환경에서 빌드한다.
- 릴리스 사전검사는 PySide6가 없거나 PyQt6가 함께 설치된 환경을 차단한다.
- PyInstaller onedir와 Inno Setup 구조는 유지한다.
- `src`와 `homework_helper.pyw`에는 PyQt6, `pyqtSignal`, `pyqtSlot`, sip 의존성을 허용하지 않는다.
- `QAbstractNativeEventFilter`의 실제 `MSG` 변환은 Windows 11 실기기에서 확인한다.

## 채택 게이트

PyQt6 기준 설치본과 각 후보를 같은 Windows 11 호스트에서 각각 10회 cold start,
5분 idle 및 2시간 soak로 측정한다.

- private bytes/RSS 중앙값 증가는 `max(5%, 8 MiB)` 이내
- idle CPU 증가는 `0.2%p` 이내
- 시작 및 주요 상호작용 p95 증가는 10% 이내
- 설치 크기 증가는 5% 이내
- thread, handle, GDI 객체가 soak 동안 지속적으로 증가하지 않을 것

절전·최대절전 복귀, 다중 모니터/DPI, tray/IPC, provider timeout, 종료 중 late
signal, 녹화 및 원격 클라이언트를 함께 확인한다. QML은 이 게이트를 통과하고
블라인드 시각 평가에서 Widgets보다 최소 두 범주 이상 우수할 때만 제품 기본값으로
승격한다.

## LGPL 배포 체크리스트

- 설치본에 Qt/PySide6 저작권 고지와 LGPL 전문을 포함한다.
- 사용한 Qt/PySide6 정확한 버전과 대응 소스 취득 경로를 제공한다.
- onedir의 동적 Qt 라이브러리를 사용자가 교체할 수 있는지 설치·업데이트 정책과 함께 확인한다.
- Qt 라이브러리 자체 수정 여부와 재링크·교체를 방해하는 서명 또는 설치 제한을 검토한다.
- 상용 배포 전 최종 의무 범위는 별도 법률 검토로 확정한다.
