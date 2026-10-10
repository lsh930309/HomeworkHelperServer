# launcher.py
import subprocess
import shlex
import os
import ctypes
from typing import Optional, Tuple # 타입 힌트를 위해 추가
import psutil  # 프로세스 관리를 위해 추가
from src.utils.launcher_utils import should_restart_launcher


from src.core.launch_target import launch_target_accepts_args
from src.core.launch_policy import launch_admin_required, read_url_target


def _windows_launch_args(args: str | list[str] | tuple[str, ...] | None) -> str | None:
    if args is None:
        return None
    if isinstance(args, str):
        value = args.strip()
    else:
        value = subprocess.list2cmdline([str(item) for item in args if str(item)])
    return value or None


def _posix_launch_args(args: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if args is None:
        return []
    if isinstance(args, str):
        value = args.strip()
        return shlex.split(value, posix=True) if value else []
    return [str(item) for item in args if str(item)]


def _posix_launch_command_args(launch_command: str, extra_args: list[str]) -> list[str]:
    command_value = str(launch_command).strip()
    if os.path.exists(command_value):
        return [command_value, *extra_args]
    return [*shlex.split(command_value, posix=True), *extra_args]


class Launcher:
    def __init__(self, run_as_admin: bool = False, *, privilege_client=None):
        self.run_as_admin = run_as_admin
        self.privilege_client = privilege_client
        self.last_error = None

        # 게임 런처 프로세스명 매핑
        self.launcher_process_map = {
            'steam://': ['Steam.exe'],
            'epic://': ['EpicGamesLauncher.exe', 'EpicWebHelper.exe'],
            'uplay://': ['Uplay.exe', 'UbisoftConnect.exe'],
            'battle.net://': ['Battle.net.exe', 'Agent.exe']
        }

    def _is_process_elevated(self, pid: int) -> Optional[bool]:
        """
        특정 프로세스가 관리자 권한으로 실행 중인지 확인합니다.

        Returns:
            True: 관리자 권한으로 실행 중
            False: 일반 권한으로 실행 중
            None: 확인 실패 (접근 권한 없음 등)
        """
        if not os.name == 'nt':
            return None

        process_handle = None
        token_handle = None
        try:
            # Windows API를 사용하여 프로세스 토큰의 권한 레벨 확인
            import win32api
            import win32security
            import win32con

            # 프로세스 핸들 열기
            process_handle = win32api.OpenProcess(
                0x1000,  # PROCESS_QUERY_LIMITED_INFORMATION
                False,
                pid
            )

            # 프로세스 토큰 가져오기
            token_handle = win32security.OpenProcessToken(
                process_handle,
                win32con.TOKEN_QUERY
            )

            # 토큰의 권한 레벨 확인
            elevation = win32security.GetTokenInformation(
                token_handle,
                win32security.TokenElevation
            )

            return bool(elevation)

        except ImportError:
            print("  pywin32가 설치되지 않아 프로세스 권한 확인을 할 수 없습니다.")
            return None
        except Exception as e:
            # 접근 거부 등의 이유로 권한 확인 실패
            print(f"  프로세스 권한 확인 중 오류: {e}")
            return None
        finally:
            for handle in (token_handle, process_handle):
                if handle is not None:
                    handle.Close()

    def _find_launcher_process(self, protocol: str) -> Optional[Tuple[psutil.Process, bool]]:
        """
        특정 프로토콜에 해당하는 게임 런처 프로세스를 찾습니다.

        Returns:
            (프로세스 객체, 관리자 권한 여부) 또는 None
        """
        if protocol not in self.launcher_process_map:
            return None

        process_names = self.launcher_process_map[protocol]

        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    from src.core.process_monitor import _belongs_to_current_user_session
                    if proc.info['name'] in process_names and _belongs_to_current_user_session(proc):
                        # 프로세스 발견
                        is_elevated = self._is_process_elevated(proc.info['pid'])
                        print(f"  게임 런처 프로세스 발견: {proc.info['name']} (PID: {proc.info['pid']}, 관리자: {is_elevated})")
                        return (proc, is_elevated)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            print(f"  {protocol} 게임 런처 프로세스를 찾을 수 없습니다.")
            return None

        except Exception as e:
            print(f"  게임 런처 프로세스 검색 중 오류: {e}")
            return None

    _get_url_from_file = staticmethod(read_url_target)
    _is_admin_required = staticmethod(launch_admin_required)

    def _confirm_launcher_transition(self, launch_command: str) -> bool:
        """Keep restart decisions in the user app; never restart implicitly."""
        url = self._get_url_from_file(launch_command) if launch_command.lower().endswith(".url") else launch_command
        prefix = next((item for item in self.launcher_process_map if url and url.startswith(item)), None)
        if not prefix:
            return True
        launcher_info = self._find_launcher_process(prefix)
        if not launcher_info or launcher_info[1] is not False:
            return True
        process, _elevated = launcher_info
        callback = getattr(self, "launcher_restart_callback", None)
        if not callable(callback) or not should_restart_launcher(process) or not callback(process.name()):
            self.last_error = "일반 권한 런처가 실행 중입니다. 안전한 재시작을 사용자 화면에서 확인해야 합니다."
            return False
        # Only the existing confirmed launcher is stopped. Never escalate this
        # into a forced kill when a launcher does not exit.
        try:
            process.terminate()
            process.wait(timeout=10)
            return True
        except (psutil.NoSuchProcess,):
            return True
        except Exception as exc:
            self.last_error = f"런처 종료 실패: {exc}"
            return False

    def launch_process(self, launch_command: str, args: str | list[str] | tuple[str, ...] | None = None, *, managed_process_id: str | None = None, launch_mode: str = "auto") -> bool:
        self.last_error = None
        if not launch_command:
            self.last_error = "실행할 경로가 없습니다."
            return False
        if os.name == "nt" and self.run_as_admin:
            if not managed_process_id:
                self.last_error = "관리자 기능은 등록된 실행 대상만 사용할 수 있습니다."
                return False
            # Perform launcher safety decisions before the privileged OS step.
            if not self._confirm_launcher_transition(launch_command):
                return False
            try:
                from src.host_service.client import HostPrivilegeClient, PrivilegeServiceError, PrivilegeServiceUnavailable
                client = self.privilege_client or HostPrivilegeClient()
                response = client.launch_managed(managed_process_id, mode=launch_mode)
                self.last_error = None if response.get("accepted") else response.get("message", "권한 작업이 거부되었습니다.")
                return bool(response.get("accepted"))
            except (PrivilegeServiceError, PrivilegeServiceUnavailable) as exc:
                self.last_error = str(exc)
                return False

        accepts_args = launch_target_accepts_args(launch_command)
        launch_args = _windows_launch_args(args) if accepts_args else None
        try:
            target = launch_command
            if target.lower().endswith(".url"):
                target = self._get_url_from_file(target)
                if not target:
                    self.last_error = "바로가기 URL을 읽을 수 없습니다."
                    return False
            if os.name == "nt":
                if target.lower().endswith((".exe", ".com")):
                    command_line = subprocess.list2cmdline([target])
                    if launch_args:
                        command_line += " " + launch_args
                    # CreateProcess never asks for elevation. A manifest that
                    # requires it returns ERROR_ELEVATION_REQUIRED instead.
                    subprocess.Popen(command_line, executable=target)
                    return True
                ret = ctypes.windll.shell32.ShellExecuteW(None, "open", target, launch_args, None, 1)
                if ret <= 32:
                    self.last_error = f"실행 요청 실패: Windows 오류 {ret}"
                return ret > 32
            if launch_command.lower().endswith(".lnk"):
                self.last_error = "Windows 바로가기는 이 운영체제에서 실행할 수 없습니다."
                return False
            if launch_command.lower().endswith(".url"):
                import webbrowser
                return bool(webbrowser.open(target))
            extra_args = _posix_launch_args(args) if accepts_args else []
            subprocess.Popen(_posix_launch_command_args(target, extra_args))
            return True
        except Exception as exc:
            if getattr(exc, "winerror", None) == 740:
                self.last_error = "이 실행 대상은 관리자 권한이 필요합니다. 관리자 기능과 권한 서비스를 사용해 주세요."
            else:
                self.last_error = str(exc)
            return False
