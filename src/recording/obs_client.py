import json
import hashlib
import base64
import threading
import time
import uuid
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import websocket
    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False


class OBSClient:
    """
    obs-websocket 5.x 최소 클라이언트.
    별도 daemon 스레드에서 WebSocket 연결 유지.
    """

    def __init__(self) -> None:
        self._host = "localhost"
        self._port = 4455
        self._password = ""
        self._ws: Optional["websocket.WebSocketApp"] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._connected = False
        self._identified = False
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Event] = {}
        self._pending_results: dict[str, dict] = {}
        self._on_record_state_changed: Optional[Callable[[bool], None]] = None
        self._stop_event = threading.Event()

    # ---------- public API ----------

    def connect(self, host: str = "localhost", port: int = 4455, password: str = "") -> bool:
        """연결 시도. 최대 5초 대기. 성공 시 True."""
        if not _WS_AVAILABLE:
            logger.warning("websocket-client not installed")
            return False
        self._host = host
        self._port = port
        self._password = password
        self._stop_event.clear()
        self._identified = False

        ready = threading.Event()
        self._ready_event = ready

        url = f"ws://{host}:{port}"
        self._ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws_thread = threading.Thread(
            target=self._ws.run_forever, daemon=True
        )
        self._ws_thread.start()
        return ready.wait(timeout=5.0) and self._identified

    def disconnect(self) -> None:
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def is_connected(self) -> bool:
        return self._identified

    def start_record(self) -> bool:
        return self._request("StartRecord") is not None

    def stop_record(self) -> bool:
        return self._request("StopRecord") is not None

    def get_record_status(self) -> dict:
        """{'outputActive': bool, 'outputDuration': int}"""
        resp = self._request("GetRecordStatus")
        if resp is None:
            return {"outputActive": False, "outputDuration": 0}
        return resp.get("responseData", {})

    def set_on_record_state_changed(self, fn: Callable[[bool], None]) -> None:
        self._on_record_state_changed = fn

    # ---------- internal ----------

    def _request(self, request_type: str, data: Optional[dict] = None) -> Optional[dict]:
        if not self._identified:
            return None
        req_id = str(uuid.uuid4())
        payload = {
            "op": 6,
            "d": {
                "requestType": request_type,
                "requestId": req_id,
                "requestData": data or {},
            },
        }
        ev = threading.Event()
        self._pending[req_id] = ev
        try:
            self._ws.send(json.dumps(payload))
        except Exception:
            self._pending.pop(req_id, None)
            return None
        if ev.wait(timeout=5.0):
            return self._pending_results.pop(req_id, None)
        self._pending.pop(req_id, None)
        return None

    def _authenticate(self, challenge: str, salt: str) -> str:
        secret = base64.b64encode(
            hashlib.sha256((self._password + salt).encode()).digest()
        ).decode()
        auth = base64.b64encode(
            hashlib.sha256((secret + challenge).encode()).digest()
        ).decode()
        return auth

    def _on_open(self, ws) -> None:
        with self._lock:
            self._connected = True

    def _on_message(self, ws, message: str) -> None:
        try:
            msg = json.loads(message)
        except Exception:
            return
        op = msg.get("op")
        d = msg.get("d", {})

        if op == 0:  # Hello
            identify = {"op": 1, "d": {"rpcVersion": 1, "eventSubscriptions": 64}}
            auth_obj = d.get("authentication")
            if auth_obj and self._password:
                identify["d"]["authentication"] = self._authenticate(
                    auth_obj["challenge"], auth_obj["salt"]
                )
            ws.send(json.dumps(identify))

        elif op == 2:  # Identified
            self._identified = True
            if hasattr(self, "_ready_event"):
                self._ready_event.set()

        elif op == 7:  # RequestResponse
            req_id = d.get("requestId")
            if req_id and req_id in self._pending:
                self._pending_results[req_id] = d
                self._pending[req_id].set()
                self._pending.pop(req_id, None)

        elif op == 5:  # Event
            event_type = d.get("eventType")
            if event_type == "RecordStateChanged":
                active = d.get("eventData", {}).get("outputActive", False)
                if self._on_record_state_changed:
                    self._on_record_state_changed(active)

    def _on_error(self, ws, error) -> None:
        logger.debug("OBS WebSocket error: %s", error)

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        self._identified = False
        self._connected = False
        if hasattr(self, "_ready_event") and not self._ready_event.is_set():
            self._ready_event.set()
