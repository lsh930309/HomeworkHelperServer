from pathlib import Path

from src.core import instance_manager


def test_windows_executable_identity_is_case_insensitive_and_path_scoped():
    first = instance_manager.instance_identity(
        r"C:\Program Files\HomeworkHelper\homework_helper.exe",
        windows=True,
    )
    same = instance_manager.instance_identity(
        r"c:\PROGRAM FILES\HomeworkHelper\.\homework_helper.exe",
        windows=True,
    )
    other = instance_manager.instance_identity(
        r"D:\Portable\HomeworkHelper\homework_helper.exe",
        windows=True,
    )

    assert first == same
    assert first.digest != other.digest
    assert first.server_name != other.server_name
    assert first.server_name.startswith(instance_manager.APP_UNIQUE_KEY + "_")


def test_single_instance_shared_memory_is_scoped_to_executable_path():
    first = instance_manager.SingleInstanceApplication(
        "test-a",
        executable_path="/install/path-a/homework_helper.exe",
    )
    first_key = first._shared_memory.key()
    first.cleanup()

    second = instance_manager.SingleInstanceApplication(
        "test-b",
        executable_path="/install/path-b/homework_helper.exe",
    )
    second_key = second._shared_memory.key()
    second.cleanup()

    assert first_key != second_key


def test_sender_routes_path_a_and_b_to_different_servers(monkeypatch):
    clients = []

    class Client:
        def __init__(self):
            self.server_name = None
            self.payload = b""

        def connectToServer(self, name):
            self.server_name = name

        def waitForConnected(self, _timeout):
            return False

    def client_factory():
        client = Client()
        clients.append(client)
        return client

    monkeypatch.setattr(instance_manager, "QLocalSocket", client_factory)

    assert instance_manager.send_instance_command(
        "show_window",
        executable_path="/install/path-a/homework_helper.exe",
    ) == instance_manager.InstanceCommandResult.NO_RUNNING_INSTANCE
    assert instance_manager.send_instance_command(
        "show_window",
        executable_path="/install/path-b/homework_helper.exe",
    ) == instance_manager.InstanceCommandResult.NO_RUNNING_INSTANCE

    assert clients[0].server_name != clients[1].server_name


def test_sender_treats_ack_for_other_path_as_unsafe_target(monkeypatch):
    path_a = "/install/path-a/homework_helper.exe"
    path_b = "/install/path-b/homework_helper.exe"
    identity_b = instance_manager.instance_identity(path_b)

    class Client:
        def connectToServer(self, _name):
            return None

        def waitForConnected(self, _timeout):
            return True

        def write(self, _payload):
            return None

        def waitForBytesWritten(self, _timeout):
            return True

        def waitForReadyRead(self, _timeout):
            return True

        def readAll(self):
            return f"ack:{identity_b.digest}:show_window\n".encode("utf-8")

        def disconnectFromServer(self):
            return None

    monkeypatch.setattr(instance_manager, "QLocalSocket", Client)

    result = instance_manager.send_instance_command(
        "show_window",
        executable_path=path_a,
    )

    assert result == instance_manager.InstanceCommandResult.UNSAFE_TARGET


def test_ipc_server_retry_never_falls_back_to_global_unscoped_key():
    source = Path("src/core/instance_manager.py").read_text(encoding="utf-8")

    assert ".listen(APP_UNIQUE_KEY)" not in source
    assert ".removeServer(APP_UNIQUE_KEY)" not in source
