# Windows PySide6 Widgets 실행·검증 계약

## 단일 실행 경로

Windows GUI는 **PySide6 + Qt Widgets**만 사용한다. MainWindow를 직접 생성하고
tray·IPC·알림도 같은 창을 표시한다. 사이드바·볼륨·스크린샷·녹화·정상 종료를 유지한다.
QML 후보 화면·Facade·투영·타이머·엔진·대체 창 포인터와 renderer 옵션 및 환경변수를
제거한다. 선택기·호환 분기·자동 복귀는 남기지 않는다.

PySide6는 Qt 6의 Python 바인딩이다. 필요한 Core·Gui·Widgets·Network를 유지하며
QML·Quick은 패키지에서 고정 제외한다. 새 프레임워크는 도입하지 않는다.

## 런타임과 패키징

- Python 3.14, PySide6==6.11.1의 깨끗한 환경과 PyInstaller onedir·Inno Setup을 유지한다.
- PyQt6 동시 설치 거부와 제품의 PyQt/sip 의존성 금지 검사는 유지한다.
- 신규 heartbeat·API 기본값·진단은 pyside6와 widgets로 통일한다. 기존 기록은 재작성하지 않는다.
- 후보 빌드 옵션·테스트·활성 PyQt 표기는 제거하고 Qt Network의 단일 인스턴스 IPC는 유지한다.
- GUI 종료는 MainWindow에서 native filter·timer·tray·sidebar·녹화·follow-up·worker를 정리한다.

## 네이티브 복귀와 실기기 검증

QAbstractNativeEventFilter는 PySide6의 QByteArray/bytes 실제 값으로 이벤트 이름을
해석한다. 실제 MSG의 WM_POWERBROADCAST와 복귀 코드 0x12를 기존 복귀 처리와
API·감시·출석 후속 갱신에 연결한다. 별도 복귀 상태는 저장하지 않는다.

합성 메시지는 실제 Windows QPA/MSG 경계를 검증한다. 물리 절전·복귀는 운영 GUI 로그와
OS 이벤트를 함께 확인하고 [호스트 계약](windows-host-lifecycle.md#마지막-전원-진단)의
마지막 단계에서 수행한다. offscreen·합성 메시지·사용자 데스크톱 검수는 구분한다.
Widgets 시작, tray 숨김·복원, IPC/알림, sidebar·volume·screenshot·recording·종료 중
late callback을 직접 관련 자동 검증과 실제 Windows로 확인한다.
테스트 Python 자식과 부모 수집은 UTF-8로 맞추며 디코딩 오류를 조용히 치환하지 않는다.

## 배포 고지

Qt/PySide6 저작권·LGPL 전문, 정확한 버전과 대응 소스 취득 경로를 제공한다.
onedir 동적 Qt 라이브러리 교체 가능성과 설치·업데이트 정책을 유지한다.
