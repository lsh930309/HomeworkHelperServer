# notifier.py
from windows_toasts import InteractableWindowsToaster, Toast, ToastButton, ToastActivatedEventArgs
from typing import Optional, Callable, Dict
import urllib.parse

class Notifier:
    def __init__(self, application_name: str = "게임 매니저", 
                 main_window_activated_callback: Optional[Callable[[Optional[str], Optional[str]], None]] = None):
        self.application_name = application_name
        self.main_window_activated_callback = main_window_activated_callback # MainWindow의 메소드를 저장
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
            if task_id_to_highlight: base_args_dict['task_id'] = task_id_to_highlight
            else: base_args_dict['task_id'] = 'NONE'

            def internal_activated_handler(event_args: ToastActivatedEventArgs):
                received_arg_string = event_args.arguments
                print(f"Toast activated. Received arguments string: '{received_arg_string}'")
                parsed_args = self._parse_arguments_string(received_arg_string)
                final_task_id = parsed_args.get('task_id')
                source = parsed_args.get('source')
                if final_task_id == 'NONE': final_task_id = None
                if self.main_window_activated_callback:
                    self.main_window_activated_callback(final_task_id, source)

            new_toast.on_activated = internal_activated_handler
            new_toast.launch_args = urllib.parse.urlencode({**base_args_dict, 'source': 'body'})
            if button_text:
                # 버튼 클릭 시 source를 button_action으로 지정
                button_args_str = urllib.parse.urlencode({**base_args_dict, 'source': button_action or 'run'})
                button = ToastButton(content=button_text, arguments=button_args_str)
                new_toast.AddAction(button)
        try:
            self.toaster.show_toast(new_toast)
            print(f"알림 표시됨 (windows-toasts): '{title}' (클릭 콜백 {'설정됨' if self.main_window_activated_callback else '없음'})")
        except Exception as e:
            print(f"알림 전송 실패 (windows-toasts): {e}")