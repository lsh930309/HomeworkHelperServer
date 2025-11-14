# notifier.py
from windows_toasts import InteractableWindowsToaster, Toast, ToastButton, ToastActivatedEventArgs
from typing import Optional, Callable, Dict
import urllib.parse
from PyQt6.QtCore import QObject, pyqtSignal

class NotificationSignalBridge(QObject):
    """
    백그라운드 스레드(Windows COM 스레드)와 메인 GUI 스레드 간의 스레드-안전 통신 브릿지.
    Toast 알림의 콜백은 백그라운드 스레드에서 실행되므로, 직접 GUI를 조작하면 충돌 발생.
    시그널/슬롯 메커니즘을 통해 메인 스레드로 안전하게 전달합니다.
    """
    # 메인 스레드에서 처리할 알림 활성화 이벤트 시그널
    notification_activated = pyqtSignal(str, str)  # (task_id, source)

    def on_notification_callback(self, event_args: ToastActivatedEventArgs):
        """
        백그라운드 스레드에서 호출될 콜백 함수.
        GUI를 직접 조작하지 않고, 시그널만 발생시켜 메인 스레드로 작업을 위임합니다.
        """
        try:
            received_arg_string = event_args.arguments
            print(f"[NotificationBridge-BG Thread] Toast activated. Arguments: '{received_arg_string}'")

            # 인자 파싱
            params = {}
            if received_arg_string:
                try:
                    pairs = received_arg_string.split('&')
                    for pair in pairs:
                        if '=' in pair:
                            key, value = pair.split('=', 1)
                            params[urllib.parse.unquote_plus(key)] = urllib.parse.unquote_plus(value)
                except Exception as e:
                    print(f"[NotificationBridge] 인자 파싱 오류: {e}")

            task_id = params.get('task_id', 'NONE')
            source = params.get('source', 'body')

            # task_id가 'NONE'이면 None으로 변환
            if task_id == 'NONE':
                task_id = None

            # 시그널 발생 (메인 스레드로 전달)
            print(f"[NotificationBridge-BG Thread] Emitting signal: task_id={task_id}, source={source}")
            self.notification_activated.emit(task_id or '', source)

        except Exception as e:
            print(f"[NotificationBridge] 콜백 처리 중 오류: {e}")

class Notifier:
    def __init__(self, application_name: str = "게임 매니저",
                 main_window_activated_callback: Optional[Callable[[Optional[str], Optional[str]], None]] = None):
        self.application_name = application_name
        self.main_window_activated_callback = main_window_activated_callback # MainWindow의 메소드를 저장

        # 스레드 안전성을 위한 시그널 브릿지 생성 (GC 방지를 위해 인스턴스 변수로 저장)
        self.signal_bridge = NotificationSignalBridge()

        # 시그널을 메인 콜백에 연결 (메인 스레드에서 안전하게 실행됨)
        if self.main_window_activated_callback:
            self.signal_bridge.notification_activated.connect(
                lambda task_id, source: self.main_window_activated_callback(
                    task_id if task_id else None,
                    source
                )
            )

        try:
            self.toaster = InteractableWindowsToaster(application_name) # InteractableToaster 사용
        except Exception as e:
            print(f"InteractableWindowsToaster 초기화 실패: {e}. 알림 기능이 작동하지 않을 수 있습니다.")
            self.toaster = None

    def _parse_arguments_string(self, arg_string: Optional[str]) -> Dict[str, str]: # 이전과 동일
        params = {};
        if not arg_string: return params
        try:
            if arg_string is None: return params
            pairs = arg_string.split('&')
            for pair in pairs:
                if '=' in pair: key, value = pair.split('=', 1); params[urllib.parse.unquote_plus(key)] = urllib.parse.unquote_plus(value)
        except Exception as e: print(f"Error parsing arguments string '{arg_string}': {e}")
        return params

    def send_notification(self,
                          title: str,
                          message: str,
                          task_id_to_highlight: Optional[str] = None,
                          button_text: Optional[str] = None,
                          button_action: Optional[str] = None):
        # button_action: 버튼 클릭 시 전달할 source 값 (예: 'run')
        if not self.toaster:
            print("Notifier가 올바르게 초기화되지 않았습니다. (콘솔 대체 알림)")
            print(f"[알림-대체] 제목: {self.application_name}: {title}")
            print(f"[알림-대체] 내용: {message}")
            if self.main_window_activated_callback and task_id_to_highlight:
                print(f"[알림-대체] 클릭 시 전달될 작업 ID (시뮬레이션): {task_id_to_highlight}")
            return

        print(f"알림 요청 (windows-toasts): '{title}' - '{message}'")
        new_toast = Toast()
        new_toast.text_fields = [title, message]

        if self.main_window_activated_callback:
            base_args_dict = {}
            if task_id_to_highlight:
                base_args_dict['task_id'] = task_id_to_highlight
            else:
                base_args_dict['task_id'] = 'NONE'

            # 스레드 안전성: 브릿지의 콜백 메서드를 사용 (백그라운드 스레드 → 시그널 → 메인 스레드)
            new_toast.on_activated = self.signal_bridge.on_notification_callback
            new_toast.launch_args = urllib.parse.urlencode({**base_args_dict, 'source': 'body'})

            if button_text:
                # 버튼 클릭 시 source를 button_action으로 지정
                button_args_str = urllib.parse.urlencode({**base_args_dict, 'source': button_action or 'run'})
                button = ToastButton(content=button_text, arguments=button_args_str)
                new_toast.AddAction(button)

        try:
            self.toaster.show_toast(new_toast)
            print(f"알림 표시됨 (windows-toasts): '{title}' (스레드 안전 콜백 {'설정됨' if self.main_window_activated_callback else '없음'})")
        except Exception as e:
            print(f"알림 전송 실패 (windows-toasts): {e}")