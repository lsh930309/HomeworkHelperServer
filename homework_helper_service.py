"""SCM service, fixed local control CLI and single-use user Shell worker.

No import here loads Qt, the API server or the application's database writer.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from queue import SimpleQueue
import sys
from threading import Event, Thread
import time

from src.host_service.constants import SERVICE_DISPLAY_NAME, SERVICE_NAME


def service_class():
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    class HomeworkHelperPrivilegeService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY_NAME
        _svc_description_ = "HomeworkHelper registered user privilege operations without interactive UAC"
        _exe_name_ = sys.executable

        def __init__(self, args):
            self.stop_event = win32event.CreateEvent(None, True, False, None)
            self.startup_stop = Event()
            self.session_events = SimpleQueue()
            self.controller = None
            # ServiceFramework registers SCM callbacks in its constructor.
            super().__init__(args)

        def GetAcceptedControls(self):
            return super().GetAcceptedControls() | win32service.SERVICE_ACCEPT_SESSIONCHANGE

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self.startup_stop.set()
            win32event.SetEvent(self.stop_event)

        def SvcShutdown(self):
            self.SvcStop()

        def SvcOtherEx(self, control, event_type, data):
            if control != win32service.SERVICE_CONTROL_SESSIONCHANGE:
                return
            # pywin32 supplies WTSSESSION_NOTIFICATION as the single-element tuple.
            session_id = int(data[0])
            event = {2:"disconnect", 5:"logon", 6:"logoff"}.get(event_type)
            if event is not None:
                # Available from __init__, so initialization never drops a new logon.
                self.session_events.put((event, session_id, time.monotonic()))

        def SvcDoRun(self):
            from src.host_service.controller import PrivilegeController
            from src.host_service.repository import ReadOnlyUserRepository
            from src.host_service.transport import NamedPipeServer
            from src.host_service.windows_backend import WindowsBackend, read_owner_sid

            install_dir = Path(sys.executable).resolve().parent
            backend = WindowsBackend(install_dir)
            owner_sid = read_owner_sid()
            if not owner_sid:
                raise RuntimeError("권한 서비스의 설치 사용자 SID가 없습니다.")
            self.controller = PrivilegeController(
                owner_sid, install_dir, backend, ReadOnlyUserRepository(),
                session_events=self.session_events, log_error=servicemanager.LogErrorMsg,
            )
            startup_worker = Thread(target=self.controller.run_session_startup,
                                    args=(self.startup_stop,), name="logon-startup", daemon=True)
            startup_worker.start()
            servicemanager.LogInfoMsg(f"{SERVICE_NAME} ready")
            try:
                NamedPipeServer(self.controller, self.stop_event, log_error=servicemanager.LogErrorMsg).run()
            finally:
                self.startup_stop.set()
                startup_worker.join(timeout=5)
                if startup_worker.is_alive():
                    servicemanager.LogErrorMsg(f"{SERVICE_NAME} login worker did not stop within 5s")

    HomeworkHelperPrivilegeService.__module__ = "homework_helper_service"
    return HomeworkHelperPrivilegeService


def stop_service(*, timeout=30):
    import win32service
    import win32serviceutil

    try:
        state = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
        if state != win32service.SERVICE_STOPPED:
            if state != win32service.SERVICE_STOP_PENDING:
                win32serviceutil.StopService(SERVICE_NAME)
            deadline = time.monotonic() + timeout
            while win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1] != win32service.SERVICE_STOPPED:
                if time.monotonic() >= deadline:
                    raise TimeoutError("권한 서비스가 제한 시간 내 중지되지 않았습니다.")
                time.sleep(0.2)
    except OSError as error:
        if getattr(error, "winerror", error.args[0]) != 1060:
            raise


def install_service(owner: str):
    if not getattr(sys, "frozen", False):
        raise RuntimeError("서명된 배포 실행 파일에서만 서비스를 설치할 수 있습니다.")
    import win32service
    import win32serviceutil
    from src.host_service.windows_backend import validate_protected_install, write_owner_sid

    validate_protected_install(Path(sys.executable).resolve())

    cls = service_class()
    stop_service()
    options = dict(startType=win32service.SERVICE_AUTO_START, exeName=str(Path(sys.executable).resolve()),
                   description=cls._svc_description_)
    try:
        win32serviceutil.InstallService("homework_helper_service.HomeworkHelperPrivilegeService",
                                       SERVICE_NAME, SERVICE_DISPLAY_NAME, **options)
    except OSError as error:
        if getattr(error, "winerror", error.args[0]) != 1073:
            raise
        win32serviceutil.ChangeServiceConfig("homework_helper_service.HomeworkHelperPrivilegeService",
                                            SERVICE_NAME, displayName=SERVICE_DISPLAY_NAME, **options)
    write_owner_sid(owner)
    manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    try:
        handle = win32service.OpenService(manager, SERVICE_NAME, win32service.SERVICE_CHANGE_CONFIG)
        try:
            win32service.ChangeServiceConfig2(handle, win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
                                             {"ResetPeriod":86400, "RebootMsg":"", "Command":"",
                                              "Actions":[(win32service.SC_ACTION_RESTART, 5000),
                                                         (win32service.SC_ACTION_RESTART, 15000),
                                                         (win32service.SC_ACTION_NONE, 0)]})
        finally:
            win32service.CloseServiceHandle(handle)
    finally:
        win32service.CloseServiceHandle(manager)
    win32serviceutil.StartService(SERVICE_NAME)
    win32serviceutil.WaitForServiceStatus(SERVICE_NAME, win32service.SERVICE_RUNNING, 30)


def uninstall_service():
    import win32serviceutil
    from src.host_service.windows_backend import remove_owner_sid

    stop_service()
    remove_owner_sid()
    try:
        win32serviceutil.RemoveService(SERVICE_NAME)
    except OSError as error:
        if getattr(error, "winerror", error.args[0]) != 1060:
            raise


def user_launch(payload: str):
    """Already selected user token; never calls runas or reads/writes user DB."""
    import win32api
    import win32con
    import win32process
    from win32com.shell import shell, shellcon

    data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    if not isinstance(data, dict) or set(data) != {"target", "args"}:
        raise ValueError("사용자 작업 입력 형식이 올바르지 않습니다.")
    target, args = data["target"], data["args"]
    if not isinstance(target, str) or not target or (args is not None and not isinstance(args, str)):
        raise ValueError("사용자 작업 실행 대상이 올바르지 않습니다.")
    from src.core.launch_target import launch_target_accepts_args
    if launch_target_accepts_args(target) and Path(target).suffix.lower() == ".exe":
        import subprocess
        # Unlike ShellExecute(open), CreateProcess never requests an interactive elevation.
        command = subprocess.list2cmdline([target]) + (" " + args if args else "")
        process, thread, _pid, _tid = win32process.CreateProcess(
            target, command, None, None, False, 0, None, str(Path(target).parent),
            win32process.STARTUPINFO(),
        )
        win32api.CloseHandle(thread)
        win32api.CloseHandle(process)
        return
    result = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS | shellcon.SEE_MASK_FLAG_DDEWAIT |
                                 shellcon.SEE_MASK_FLAG_NO_UI,
                                 lpVerb="open", lpFile=target, lpParameters=args,
                                 nShow=win32con.SW_SHOWNORMAL)
    handle = result.get("hProcess")
    if handle:
        win32api.CloseHandle(handle)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="HomeworkHelper Windows privilege service")
    commands = parser.add_subparsers(dest="command")
    install = commands.add_parser("install")
    install.add_argument("--owner", required=True)
    commands.add_parser("uninstall")
    commands.add_parser("stop")
    parser.add_argument("--control", choices=("status", "power"))
    parser.add_argument("action", nargs="?", choices=("shutdown", "restart", "sleep"))
    parser.add_argument("--user-launch", metavar="PAYLOAD")
    # Subparsers followed by a positional would treat `--control power sleep` as a command.
    # Parse fixed control/user-worker forms separately rather than accepting arbitrary commands.
    values = list(sys.argv[1:] if argv is None else argv)
    try:
        if values[:1] == ["--control"]:
            control = argparse.ArgumentParser(description="Local authenticated service control")
            control.add_argument("--control", required=True, choices=("status", "power"))
            control.add_argument("action", nargs="?", choices=("shutdown", "restart", "sleep"))
            args = control.parse_args(values)
            if (args.control == "power") != (args.action is not None):
                control.error("power에는 action이 필요하고 status에는 action을 사용할 수 없습니다.")
            from src.host_service.client import HostPrivilegeClient
            if args.control == "power":
                def emit_before_ack(result):
                    if result.get("accepted") is True:
                        # Write the SSH-visible receipt before service power is released by ACK.
                        # ASCII JSON survives Windows console code pages; JSON restores the text.
                        print(json.dumps(result, ensure_ascii=True), flush=True)
                HostPrivilegeClient(before_ack=emit_before_ack).control_power(args.action)
            else:
                result = HostPrivilegeClient().status()
                print(json.dumps(result, ensure_ascii=True), flush=True)
            return 0
        if values[:1] == ["--user-launch"]:
            if len(values) != 2:
                raise ValueError("사용자 작업 입력 하나가 필요합니다.")
            user_launch(values[1])
            return 0
        args = parser.parse_args(values)
        if os.name != "nt":
            raise OSError("이 실행 파일은 Windows에서만 사용할 수 있습니다.")
        if args.command == "install":
            install_service(args.owner)
        elif args.command == "uninstall":
            uninstall_service()
        elif args.command == "stop":
            stop_service()
        elif not values:
            import servicemanager
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(service_class())
            servicemanager.StartServiceCtrlDispatcher()
        else:
            parser.error("지원하지 않는 서비스 명령입니다.")
        return 0
    except Exception as error:
        from src.host_service.client import PrivilegeServiceError, PrivilegeServiceUnavailable
        status = "unavailable" if isinstance(error, PrivilegeServiceUnavailable) else (
            error.status if isinstance(error, PrivilegeServiceError) else "error")
        result = {"accepted":False, "status":status,
                  "message":str(error)}
        print(json.dumps(result, ensure_ascii=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
