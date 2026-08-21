from src.core import instance_manager


class _FakeSocket:
    def __init__(self, payload: bytes):
        self.payload = payload
        self._hh_received_command = False
        self._hh_command_buffer = bytearray()
        self.responses = []
        self.disconnected = False

    def readAll(self):
        payload, self.payload = self.payload, b""
        return payload

    def write(self, payload):
        self.responses.append(bytes(payload))

    def flush(self):
        return True

    def disconnectFromServer(self):
        self.disconnected = True

    def abort(self):
        self.disconnected = True

    def deleteLater(self):
        return None


class _Window:
    def __init__(self):
        self.shown = 0

    def activate_and_show(self):
        self.shown += 1


class _FakeClientSocket:
    def __init__(self, *, connected=True, written=True, ready=True, response=None):
        self.connected = connected
        self.written = written
        self.ready = ready
        self.response = response
        self.payload = b""
        self.aborted = False
        self.server_name = None

    def connectToServer(self, name):
        self.server_name = name

    def waitForConnected(self, _timeout):
        return self.connected

    def write(self, payload):
        self.payload = bytes(payload)

    def waitForBytesWritten(self, _timeout):
        return self.written

    def waitForReadyRead(self, _timeout):
        return self.ready

    def readAll(self):
        if self.response is None:
            identity, command = instance_manager.parse_instance_message(self.payload)
            return f"ack:{identity}:{command.value}\n".encode("utf-8")
        return self.response

    def disconnectFromServer(self):
        return None

    def abort(self):
        self.aborted = True


def _manager(window):
    manager = instance_manager.SingleInstanceApplication("test")
    manager._main_window_ref = window
    return manager


def test_parse_instance_command_accepts_only_show_window():
    assert instance_manager.parse_instance_command(b"show_window\n") == instance_manager.InstanceCommand.SHOW_WINDOW
    assert instance_manager.parse_instance_command("unsupported_command\n") is None
    assert instance_manager.parse_instance_command("show_window_now\n") is None


def test_command_sender_uses_path_scoped_identity(monkeypatch):
    client = _FakeClientSocket()
    monkeypatch.setattr(instance_manager, "QLocalSocket", lambda: client)

    result = instance_manager.send_instance_command(instance_manager.InstanceCommand.SHOW_WINDOW)

    assert result == instance_manager.InstanceCommandResult.SUCCESS
    expected_identity = instance_manager.instance_identity()
    assert client.server_name == expected_identity.server_name
    assert client.payload == instance_manager.encode_instance_command(
        instance_manager.InstanceCommand.SHOW_WINDOW,
        expected_identity,
    )
    assert int(instance_manager.send_instance_command("unknown")) == 5


def test_command_sender_distinguishes_missing_server_and_ack_timeout(monkeypatch):
    missing = _FakeClientSocket(connected=False)
    monkeypatch.setattr(instance_manager, "QLocalSocket", lambda: missing)
    assert int(instance_manager.send_instance_command("show_window")) == 3

    timeout = _FakeClientSocket(ready=False)
    monkeypatch.setattr(instance_manager, "QLocalSocket", lambda: timeout)
    assert int(instance_manager.send_instance_command("show_window")) == 4
    assert timeout.aborted is True


def test_ipc_server_dispatches_show_window_and_acknowledges():
    window = _Window()
    manager = _manager(window)
    socket = _FakeSocket(b"show_window\n")
    manager._active_client_sockets.add(socket)

    manager._read_ipc_message(socket)

    assert window.shown == 1
    assert socket.responses == [f"ack:{manager._identity.digest}:show_window\n".encode("utf-8")]
    assert socket.disconnected is True
    manager.cleanup()


def test_ipc_server_rejects_unknown_command():
    window = _Window()
    manager = _manager(window)
    socket = _FakeSocket(b"unsupported_command\n")
    manager._active_client_sockets.add(socket)

    manager._read_ipc_message(socket)

    assert socket.responses == [b"error:unsafe_target\n"]
    assert window.shown == 0
    manager.cleanup()


def test_legacy_blind_connection_still_activates_window():
    window = _Window()
    manager = _manager(window)
    socket = _FakeSocket(b"")
    manager._active_client_sockets.add(socket)

    manager._handle_blind_ipc_connection(socket)

    assert window.shown == 1
    assert socket.disconnected is True
    manager.cleanup()
