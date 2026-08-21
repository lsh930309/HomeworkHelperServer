# instance_manager.py
import sys
import hashlib
import ntpath
import os
from dataclasses import dataclass
from enum import Enum, IntEnum

from PySide6.QtCore import QSharedMemory, QObject, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QMessageBox

# 애플리케이션 고유 키 (다른 애플리케이션과 충돌하지 않도록 유니크하게 설정하세요)
APP_UNIQUE_KEY = "HomeworkHelper_App_UUID_v1.0_KHS_UniqueInstanceKey"
IPC_PROTOCOL_VERSION = "HHIPC1"


@dataclass(frozen=True)
class InstanceIdentity:
    normalized_executable_path: str
    digest: str
    server_name: str


def normalize_executable_path(executable_path: str | os.PathLike[str], *, windows: bool | None = None) -> str:
    """Return the stable executable identity path used by shared memory and IPC."""
    raw_path = os.fspath(executable_path)
    windows = os.name == "nt" if windows is None else bool(windows)
    if windows:
        if os.name == "nt":
            raw_path = os.path.realpath(os.path.abspath(raw_path))
        return ntpath.normcase(ntpath.normpath(ntpath.abspath(raw_path)))
    return os.path.normcase(os.path.realpath(os.path.abspath(raw_path)))


def instance_identity(
    executable_path: str | os.PathLike[str] | None = None,
    *,
    windows: bool | None = None,
) -> InstanceIdentity:
    normalized_path = normalize_executable_path(executable_path or sys.executable, windows=windows)
    digest = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:20]
    return InstanceIdentity(
        normalized_executable_path=normalized_path,
        digest=digest,
        server_name=f"{APP_UNIQUE_KEY}_{digest}",
    )


class InstanceCommand(str, Enum):
    SHOW_WINDOW = "show_window"


class InstanceCommandResult(IntEnum):
    SUCCESS = 0
    NO_RUNNING_INSTANCE = 3
    TIMEOUT = 4
    UNSAFE_TARGET = 5


def parse_instance_command(payload: bytes | str) -> InstanceCommand | None:
    """Parse one newline-delimited IPC command without accepting prefixes."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    command = payload.splitlines()[0].strip() if payload.splitlines() else payload.strip()
    try:
        return InstanceCommand(command)
    except ValueError:
        return None


def encode_instance_command(command: InstanceCommand, identity: InstanceIdentity) -> bytes:
    return f"{IPC_PROTOCOL_VERSION} {identity.digest} {command.value}\n".encode("utf-8")


def parse_instance_message(payload: bytes | str) -> tuple[str | None, InstanceCommand | None]:
    """Parse the versioned protocol while retaining legacy show-window messages."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    line = payload.splitlines()[0].strip() if payload.splitlines() else payload.strip()
    parts = line.split()
    if len(parts) == 3 and parts[0] == IPC_PROTOCOL_VERSION:
        try:
            return parts[1], InstanceCommand(parts[2])
        except ValueError:
            return parts[1], None
    return None, parse_instance_command(line)


def send_instance_command(
    command: InstanceCommand | str,
    *,
    executable_path: str | os.PathLike[str] | None = None,
    connect_timeout_ms: int = 500,
    ack_timeout_ms: int = 1500,
) -> InstanceCommandResult:
    """Send a command to the primary process and wait for its explicit ACK."""
    try:
        parsed_command = command if isinstance(command, InstanceCommand) else InstanceCommand(command)
    except ValueError:
        return InstanceCommandResult.UNSAFE_TARGET

    identity = instance_identity(executable_path)
    ipc_socket = QLocalSocket()
    ipc_socket.connectToServer(identity.server_name)
    if not ipc_socket.waitForConnected(connect_timeout_ms):
        return InstanceCommandResult.NO_RUNNING_INSTANCE

    ipc_socket.write(encode_instance_command(parsed_command, identity))
    if not ipc_socket.waitForBytesWritten(min(ack_timeout_ms, 500)):
        ipc_socket.abort()
        return InstanceCommandResult.TIMEOUT
    if not ipc_socket.waitForReadyRead(ack_timeout_ms):
        ipc_socket.abort()
        return InstanceCommandResult.TIMEOUT

    response = bytes(ipc_socket.readAll()).decode("utf-8", errors="replace").strip()
    ipc_socket.disconnectFromServer()
    if response == f"ack:{identity.digest}:{parsed_command.value}":
        return InstanceCommandResult.SUCCESS
    if response == "error:unsafe_target":
        return InstanceCommandResult.UNSAFE_TARGET
    if response.startswith("ack:"):
        return InstanceCommandResult.UNSAFE_TARGET
    return InstanceCommandResult.TIMEOUT


class SingleInstanceApplication(QObject):
    """
    애플리케이션의 단일 실행을 관리하고, 중복 실행 시 기존 인스턴스를 활성화합니다.
    QObject를 상속받아 내부적으로 QLocalServer의 시그널 등을 처리할 수 있습니다.
    """
    _instance_manager_singleton = None # 클래스 레벨에서 싱글턴 인스턴스 관리 (선택적)

    def __init__(
        self,
        application_name: str = "Application",
        *,
        executable_path: str | os.PathLike[str] | None = None,
    ):
        super().__init__()
        # 이 클래스의 인스턴스는 애플리케이션 전체에서 하나만 존재해야 함
        if SingleInstanceApplication._instance_manager_singleton is not None:
            # 이 부분은 run_single_instance_application 함수를 통해 호출되므로,
            # 직접적인 다중 생성은 없을 것으로 예상되나 방어적으로 추가.
            print("경고: SingleInstanceApplication은 이미 생성되었습니다.")
            # raise RuntimeError("SingleInstanceApplication should only be created once.")
        SingleInstanceApplication._instance_manager_singleton = self
        
        self.application_name = application_name
        self._identity = instance_identity(executable_path)
        self._executable_path = self._identity.normalized_executable_path
        self._shared_memory = QSharedMemory(self._identity.server_name)
        self._local_server = None
        self._main_window_ref = None # 활성화할 메인 윈도우 참조
        self._active_client_sockets = set()

    def is_primary_instance(self) -> bool:
        """이것이 주 인스턴스인지 확인합니다. 공유 메모리를 연결하거나 생성합니다."""
        # 읽기 전용으로 연결 시도 (이미 실행 중인 인스턴스가 있는지 확인)
        if self._shared_memory.attach(QSharedMemory.AccessMode.ReadOnly):
            print("공유 메모리 연결 성공. 다른 인스턴스가 이미 실행 중입니다.")
            return False # 다른 인스턴스가 주 인스턴스임

        # 주 인스턴스가 아닌 경우, 공유 메모리 생성 시도
        # (혹시 모를 이전 상태 정리를 위해 detach 후 create 시도)
        self._shared_memory.detach()
        if not self._shared_memory.create(1024): # 최소 크기로 세그먼트 생성
            # 생성 실패 원인 확인 (예: 경쟁 상태로 다른 인스턴스가 방금 생성)
            if self._shared_memory.error() == QSharedMemory.SharedMemoryError.AlreadyExists:
                print("공유 메모리 생성 실패 (AlreadyExists). 다른 인스턴스가 방금 시작했을 수 있습니다.")
                # 이 경우, 이 인스턴스는 보조 인스턴스로 간주하고 기존 인스턴스에 시그널링 시도
                return False
            else:
                # 그 외 치명적인 오류
                QMessageBox.critical(None, f"{self.application_name} - 실행 오류",
                                     f"공유 메모리 생성에 실패했습니다: {self._shared_memory.errorString()}\n"
                                     "프로그램을 시작할 수 없습니다.")
                sys.exit(1) # 프로그램 비정상 종료

        print("공유 메모리 생성 성공. 이 인스턴스가 주 인스턴스입니다.")
        return True # 이 인스턴스가 주 인스턴스임

    def signal_existing_instance_and_exit(self):
        """이미 실행 중인 주 인스턴스에 활성화 신호를 보내고 현재 인스턴스를 종료합니다."""
        print(f"{self.application_name}: 이미 실행 중인 인스턴스에 활성화 요청을 보냅니다...")
        result = send_instance_command(
            InstanceCommand.SHOW_WINDOW,
            executable_path=self._executable_path,
        )
        if result == InstanceCommandResult.SUCCESS:
            print("활성화 요청 전송 완료.")
        else:
            print(f"기존 인스턴스의 IPC 요청 실패: {result.name}")
            QMessageBox.warning(None, f"{self.application_name} - 실행 중",
                                "프로그램이 이미 실행 중이지만, 창을 자동으로 활성화할 수 없었습니다.\n"
                                "이미 실행된 창을 직접 찾아주세요.")
        sys.exit(0) # 현재 (보조) 인스턴스 종료

    def start_ipc_server(self, main_window_to_activate):
        """주 인스턴스에서 IPC 서버를 시작하여 다른 인스턴스로부터의 연결을 수신합니다."""
        if not main_window_to_activate:
            print("오류: IPC 서버 시작을 위한 MainWindow 참조가 없습니다.")
            return False

        self._main_window_ref = main_window_to_activate
        self._local_server = QLocalServer(self) # 부모를 self로 설정하여 자동 정리되도록 함
        self._local_server.newConnection.connect(self._handle_ipc_new_connection)

        # 서버 리슨 시도
        if not self._local_server.listen(self._identity.server_name):
            # 리슨 실패 시 (예: 이전 비정상 종료로 인한 소켓 파일 문제)
            print(f"IPC 서버 listen 실패 (1차): {self._local_server.errorString()}")
            # 기존 서버 소켓 파일 제거 시도 (주로 Unix 계열에서 효과적)
            if QLocalServer.removeServer(self._identity.server_name):
                print("기존 IPC 서버 소켓 파일 제거 시도 후 재시도...")
                if self._local_server.listen(self._identity.server_name):
                    print("IPC 서버 listen 성공 (재시도 후).")
                    return True
            # 재시도도 실패하거나 removeServer가 효과 없는 경우 (예: Windows)
            self._report_ipc_server_failure()
            return False
        else:
            print("IPC 서버 listen 성공. 다른 인스턴스로부터의 활성화 요청을 기다립니다.")
            return True

    def _report_ipc_server_failure(self):
        error_msg = self._local_server.errorString() if self._local_server else "알 수 없는 서버 오류"
        print(f"IPC 서버 listen 실패: {error_msg}")
        QMessageBox.warning(None, f"{self.application_name} - IPC 서버 오류",
                            f"IPC 서버를 시작할 수 없습니다: {error_msg}\n"
                            "다른 인스턴스에서 이 창을 자동으로 활성화하지 못할 수 있습니다.")

    def _handle_ipc_new_connection(self):
        """새로운 IPC 연결을 처리합니다 (다른 인스턴스로부터의 활성화 요청)."""
        if not self._main_window_ref:
            print("IPC: MainWindow 참조가 없어 연결을 처리할 수 없습니다.")
            socket = self._local_server.nextPendingConnection()
            if socket:
                socket.disconnectFromServer()
                socket.deleteLater() # 소켓 자원 정리
            return

        while self._local_server.hasPendingConnections():
            socket = self._local_server.nextPendingConnection()
            if not socket:
                continue
            socket._hh_received_command = False
            socket._hh_command_buffer = bytearray()
            self._active_client_sockets.add(socket)
            socket.readyRead.connect(lambda active=socket: self._read_ipc_message(active))
            socket.disconnected.connect(lambda active=socket: self._finish_ipc_connection(active))
            # Legacy clients treated connection itself as show_window and might send no payload.
            QTimer.singleShot(150, lambda active=socket: self._handle_blind_ipc_connection(active))
            if socket.bytesAvailable():
                self._read_ipc_message(socket)

    def _write_ipc_response(self, socket, response: str):
        socket.write((response + "\n").encode("utf-8"))
        socket.flush()

    def _schedule_callback(self, delay_ms: int, callback):
        QTimer.singleShot(delay_ms, callback)

    def _read_ipc_message(self, socket):
        if socket not in self._active_client_sockets or socket._hh_received_command:
            return
        socket._hh_command_buffer.extend(bytes(socket.readAll()))
        if b"\n" not in socket._hh_command_buffer:
            return
        socket._hh_received_command = True
        message_identity, command = parse_instance_message(bytes(socket._hh_command_buffer))
        if message_identity is not None and message_identity != self._identity.digest:
            self._write_ipc_response(socket, "error:unsafe_target")
            socket.disconnectFromServer()
            return
        if message_identity is None and command != InstanceCommand.SHOW_WINDOW:
            self._write_ipc_response(socket, "error:unsafe_target")
            socket.disconnectFromServer()
            return
        if command == InstanceCommand.SHOW_WINDOW:
            callback = getattr(self._main_window_ref, "activate_and_show", None)
            if not callable(callback):
                self._write_ipc_response(socket, "error:unsafe_target")
            else:
                callback()
                self._write_ipc_response(socket, f"ack:{self._identity.digest}:show_window")
        else:
            self._write_ipc_response(socket, "error:unsafe_target")
        socket.disconnectFromServer()

    def _handle_blind_ipc_connection(self, socket):
        if socket not in self._active_client_sockets or socket._hh_received_command:
            return
        socket._hh_received_command = True
        callback = getattr(self._main_window_ref, "activate_and_show", None)
        if callable(callback):
            callback()
        socket.disconnectFromServer()

    def _finish_ipc_connection(self, socket):
        if not socket._hh_received_command:
            # Compatibility with pre-command clients that used connect/disconnect as show_window.
            socket._hh_received_command = True
            callback = getattr(self._main_window_ref, "activate_and_show", None)
            if callable(callback):
                callback()
        if socket in self._active_client_sockets:
            self._active_client_sockets.remove(socket)
        socket.deleteLater()

    def cleanup(self):
        """애플리케이션 종료 시 IPC 서버 및 공유 메모리 관련 리소스를 정리합니다."""
        # 중복 호출 방지 플래그 확인
        if hasattr(self, '_cleanup_done') and self._cleanup_done:
            return

        print("InstanceManager: 리소스 정리 시작...")

        # Qt 객체는 이미 삭제되었을 수 있으므로 try-except로 보호
        try:
            if self._local_server and self._local_server.isListening():
                self._local_server.close()
                print("IPC 서버가 닫혔습니다.")
            for socket in tuple(self._active_client_sockets):
                socket.abort()
                socket.deleteLater()
            self._active_client_sockets.clear()
        except RuntimeError:
            # Qt 객체가 이미 삭제된 경우 무시
            print("IPC 서버가 이미 정리되었습니다.")

        # 공유 메모리는 이 인스턴스가 생성한 경우에만 detach/release 책임이 있음.
        # QSharedMemory 객체의 소멸자가 자동으로 처리해주지만, 명시적으로 호출 가능.
        try:
            if self._shared_memory and self._shared_memory.isAttached():
                if not self._shared_memory.detach():
                    print(f"경고: 공유 메모리 분리 실패 - {self._shared_memory.errorString()}")
                else:
                    print("공유 메모리가 분리되었습니다.")
        except RuntimeError:
            # Qt 객체가 이미 삭제된 경우 무시
            print("공유 메모리가 이미 정리되었습니다.")

        # 만약 이 인스턴스가 공유 메모리를 create 했다면, QSharedMemory 객체가 소멸될 때 OS 레벨의 세그먼트도 정리됨 (참조 카운트 기반)
        print("InstanceManager: 리소스 정리 완료.")

        # 중복 호출 방지 플래그 설정
        self._cleanup_done = True
        if SingleInstanceApplication._instance_manager_singleton is self:
            SingleInstanceApplication._instance_manager_singleton = None


def run_with_single_instance_check(application_name: str, main_app_start_callback):
    """
    단일 인스턴스 실행을 보장하는 래퍼 함수.
    - application_name: 애플리케이션 이름 (메시지 등에 사용)
    - main_app_start_callback: 주 인스턴스일 경우 호출될 함수. 
                               이 콜백은 SingleInstanceApplication 객체를 인자로 받아야 함.
    """
    instance_manager = SingleInstanceApplication(application_name)

    if instance_manager.is_primary_instance():
        # 주 인스턴스이므로, 실제 애플리케이션 실행 콜백을 호출
        # instance_manager 객체를 전달하여 IPC 서버 시작 및 종료 시 정리 로직을 수행할 수 있도록 함
        main_app_start_callback(instance_manager)
        # main_app_start_callback은 sys.exit(app.exec())를 포함해야 하며,
        # app.exec()가 반환된 후 instance_manager.cleanup()이 호출되도록 보장하는 것이 좋음.
        # (또는 MainWindow의 initiate_quit_sequence에서 cleanup 호출)
    else:
        # 이미 실행 중인 인스턴스가 있으므로, 해당 인스턴스에 신호를 보내고 현재 인스턴스는 종료
        instance_manager.signal_existing_instance_and_exit()

