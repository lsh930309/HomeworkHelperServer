# api_client.py

import requests
from typing import Any, List, Optional
import os
import uuid
from src.data.data_models import ManagedProcess, WebShortcut, GlobalSettings, ProcessSession


class BeholderIncidentRequired(requests.HTTPError):
    """Raised when the backend blocks a DB mutation and creates an incident."""

    def __init__(self, response: requests.Response, incident: dict[str, Any]):
        self.incident = incident
        super().__init__(incident.get("safe_recommendation") or response.text, response=response)


class ApiClient:
    """
    FastAPI 서버와 통신하여 데이터를 CRUD하는 클라이언트.
    기존 DataManager의 역할을 대체합니다.
    """
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        # 패키지 환경에서 동적으로 선택된 포트를 우선 사용
        dyn_port = os.environ.get("HH_API_PORT")
        if dyn_port:
            base_url = f"http://127.0.0.1:{dyn_port}"
        self.base_url = base_url
        self.app_instance_id = str(uuid.uuid4())
        self.latest_beholder_incident: dict[str, Any] | None = None
        # 최초 실행 시, 서버에서 모든 데이터를 가져와 내부 변수에 저장합니다.
        self.managed_processes: List[ManagedProcess] = self._fetch_all_processes()
        self.web_shortcuts: List[WebShortcut] = self._fetch_all_web_shortcuts()
        self.global_settings: GlobalSettings = self._fetch_global_settings()


    def _raise_for_status(self, response: requests.Response) -> None:
        if response.status_code == 409:
            try:
                body = response.json()
            except ValueError:
                body = {}
            incident = body.get("beholder_incident")
            if incident:
                self.latest_beholder_incident = incident
                raise BeholderIncidentRequired(response, incident)
        response.raise_for_status()

    def pop_latest_beholder_incident(self) -> dict[str, Any] | None:
        incident = self.latest_beholder_incident
        self.latest_beholder_incident = None
        return incident

    def get_active_beholder_incidents(self) -> list[dict[str, Any]]:
        try:
            response = requests.get(f"{self.base_url}/api/beholder/incidents/active", timeout=5)
            self._raise_for_status(response)
            return response.json().get("incidents", [])
        except requests.RequestException as e:
            print(f"Beholder incident 조회 실패: {e}")
            return []

    def resolve_beholder_incident(self, incident_id: int, action: str) -> dict[str, Any] | None:
        try:
            response = requests.post(
                f"{self.base_url}/api/beholder/incidents/{incident_id}/resolve",
                json={"action": action},
                timeout=10,
            )
            self._raise_for_status(response)
            return response.json()
        except requests.RequestException as e:
            print(f"Beholder incident 결정 저장 실패: {e}")
            return None

    def send_runtime_heartbeat(self, *, shutdown: bool = False, runtime_kind: str = "pyqt") -> dict[str, Any] | None:
        try:
            response = requests.post(
                f"{self.base_url}/api/beholder/runtime/heartbeat",
                json={"app_instance_id": self.app_instance_id, "runtime_kind": runtime_kind, "shutdown": shutdown},
                timeout=5,
            )
            self._raise_for_status(response)
            return response.json()
        except requests.RequestException as e:
            print(f"런타임 heartbeat 저장 실패: {e}")
            return None

    def reconcile_open_sessions(self, running_process_ids: list[str]) -> list[dict[str, Any]]:
        try:
            response = requests.post(
                f"{self.base_url}/api/beholder/open-sessions/reconcile",
                json={"running_process_ids": running_process_ids},
                timeout=10,
            )
            self._raise_for_status(response)
            return response.json().get("incidents", [])
        except requests.RequestException as e:
            print(f"열린 세션 복구 점검 실패: {e}")
            return []


    def get_beholder_backups(self) -> list[dict[str, Any]]:
        try:
            response = requests.get(f"{self.base_url}/api/beholder/backups", timeout=5)
            self._raise_for_status(response)
            return response.json().get("backups", [])
        except requests.RequestException as e:
            print(f"Beholder 백업 목록 조회 실패: {e}")
            return []

    def restore_beholder_backup(self, slot: int) -> dict[str, Any] | None:
        try:
            response = requests.post(
                f"{self.base_url}/api/beholder/backups/restore",
                json={"slot": slot},
                timeout=20,
            )
            self._raise_for_status(response)
            return response.json()
        except requests.RequestException as e:
            print(f"Beholder 백업 복구 실패: {e}")
            return None

    def _fetch_all_processes(self) -> List[ManagedProcess]:
        """서버에서 모든 프로세스 목록을 가져옵니다."""
        try:
            response = requests.get(f"{self.base_url}/processes", timeout=10)
            self._raise_for_status(response)  # 200번대 상태 코드가 아니면 에러 발생
            processes_data = response.json()
            # JSON 딕셔너리 리스트를 ManagedProcess 객체 리스트로 변환
            return [ManagedProcess.from_dict(p) for p in processes_data]
        except requests.RequestException as e:
            print(f"프로세스 목록을 불러오는 데 실패했습니다: {e}")
            return []

    # --- ManagedProcess 관련 메서드 ---

    def add_process(self, process: ManagedProcess) -> bool:
        """새로운 프로세스를 서버에 추가합니다."""
        try:
            # Pydantic 스키마에 맞게 id를 제외하고 데이터를 보냅니다.
            data_to_send = process.to_dict()
            if 'id' in data_to_send:
                del data_to_send['id']

            response = requests.post(f"{self.base_url}/processes", json=data_to_send, timeout=10)
            self._raise_for_status(response)
            
            # 성공 시, 내부 데이터 목록도 새로고침합니다. (전체 목록을 다시 가져오는 것이 가장 간단하고 확실함)
            self.managed_processes = self._fetch_all_processes()
            return True
        except requests.RequestException as e:
            print(f"프로세스 추가에 실패했습니다: {e}")
            return False

    def remove_process(self, process_id: str) -> bool:
        """ID로 프로세스를 서버에서 삭제합니다."""
        try:
            response = requests.delete(f"{self.base_url}/processes/{process_id}", timeout=10)
            self._raise_for_status(response)
            
            # 성공 시, 내부 데이터 목록도 새로고침합니다.
            self.managed_processes = self._fetch_all_processes()
            return True
        except requests.RequestException as e:
            print(f"프로세스 삭제에 실패했습니다: {e}")
            return False

    def update_process(self, updated_process: ManagedProcess) -> bool:
        """기존 프로세스 정보를 서버에서 업데이트합니다."""
        try:
            data_to_send = updated_process.to_dict()
            if 'id' in data_to_send:
                del data_to_send['id'] # id는 경로로 전달하므로 본문에서는 제외

            response = requests.put(f"{self.base_url}/processes/{updated_process.id}", json=data_to_send, timeout=10)
            self._raise_for_status(response)
            
            # 성공 시, 내부 데이터 목록도 새로고침합니다.
            self.managed_processes = self._fetch_all_processes()
            return True
        except requests.RequestException as e:
            print(f"프로세스 업데이트에 실패했습니다: {e}")
            return False

    def update_process_runtime_state(self, updated_process: ManagedProcess) -> bool:
        """Persist only runtime-owned process fields after monitor stop/calibration."""
        try:
            response = requests.patch(
                f"{self.base_url}/processes/{updated_process.id}/runtime-state",
                json={
                    "last_played_timestamp": updated_process.last_played_timestamp,
                    "stamina_current": updated_process.stamina_current,
                    "stamina_max": updated_process.stamina_max,
                    "stamina_updated_at": updated_process.stamina_updated_at,
                },
                timeout=10,
            )
            self._raise_for_status(response)
            self.managed_processes = self._fetch_all_processes()
            return True
        except requests.RequestException as e:
            print(f"프로세스 런타임 상태 저장에 실패했습니다: {e}")
            return False

    def get_process_by_id(self, process_id: str) -> Optional[ManagedProcess]:
        """ID로 단일 프로세스를 찾습니다 (내부 메모리에서)."""
        for p in self.managed_processes:
            if p.id == process_id:
                return p
        return None
    # --- WebShortcut 관련 메서드 ---

    def _fetch_all_web_shortcuts(self) -> List[WebShortcut]:
        """서버에서 모든 웹 바로 가기 목록을 가져옵니다."""
        try:
            response = requests.get(f"{self.base_url}/shortcuts", timeout=10)
            self._raise_for_status(response)
            shortcuts_data = response.json()
            return [WebShortcut.from_dict(sc) for sc in shortcuts_data]
        except requests.RequestException as e:
            print(f"웹 바로 가기 목록을 불러오는 데 실패했습니다: {e}")
            return []

    def add_web_shortcut(self, shortcut: WebShortcut) -> bool:
        """새로운 웹 바로 가기를 서버에 추가합니다."""
        try:
            data_to_send = shortcut.to_dict()
            if 'id' in data_to_send:
                del data_to_send['id']

            response = requests.post(f"{self.base_url}/shortcuts", json=data_to_send, timeout=10)
            self._raise_for_status(response)
            
            # 성공 시, 내부 데이터 목록도 새로고침합니다.
            self.web_shortcuts = self._fetch_all_web_shortcuts()
            return True
        except requests.RequestException as e:
            print(f"웹 바로 가기 추가에 실패했습니다: {e}")
            return False

    def remove_web_shortcut(self, shortcut_id: str) -> bool:
        """ID로 웹 바로 가기를 서버에서 삭제합니다."""
        try:
            response = requests.delete(f"{self.base_url}/shortcuts/{shortcut_id}", timeout=10)
            self._raise_for_status(response)
            
            # 성공 시, 내부 데이터 목록도 새로고침합니다.
            self.web_shortcuts = self._fetch_all_web_shortcuts()
            return True
        except requests.RequestException as e:
            print(f"웹 바로 가기 삭제에 실패했습니다: {e}")
            return False
        
    def update_web_shortcut(self, updated_shortcut: WebShortcut) -> bool:
        """기존 웹 바로 가기 정보를 서버에서 업데이트합니다."""
        try:
            data_to_send = updated_shortcut.to_dict()
            if 'id' in data_to_send:
                del data_to_send['id']

            response = requests.put(f"{self.base_url}/shortcuts/{updated_shortcut.id}", json=data_to_send, timeout=10)
            self._raise_for_status(response)
            
            # 성공 시, 내부 데이터 목록도 새로고침합니다.
            self.web_shortcuts = self._fetch_all_web_shortcuts()
            return True
        except requests.RequestException as e:
            print(f"웹 바로 가기 업데이트에 실패했습니다: {e}")
            return False

    def mark_web_shortcut_opened(self, shortcut_id: str) -> bool:
        """웹 바로가기 클릭 완료 시각을 런타임 경로로 저장합니다."""
        try:
            response = requests.post(f"{self.base_url}/shortcuts/{shortcut_id}/opened", timeout=10)
            self._raise_for_status(response)

            self.web_shortcuts = self._fetch_all_web_shortcuts()
            return True
        except requests.RequestException as e:
            print(f"웹 바로 가기 완료 시각 저장에 실패했습니다: {e}")
            return False

    def get_web_shortcut_by_id(self, shortcut_id: str) -> Optional[WebShortcut]:
        """ID로 단일 웹 바로 가기를 찾습니다 (내부 메모리에서)."""
        for sc in self.web_shortcuts:
            if sc.id == shortcut_id:
                return sc
        return None
    # --- GlobalSettings 관련 메서드 ---

    def _fetch_global_settings(self) -> GlobalSettings:
        """서버에서 전역 설정을 가져옵니다."""
        try:
            response = requests.get(f"{self.base_url}/settings", timeout=10)
            self._raise_for_status(response)
            return GlobalSettings.from_dict(response.json())
        except requests.RequestException as e:
            print(f"전역 설정을 불러오는 데 실패했습니다: {e}")
            return GlobalSettings()
        
    def save_global_settings(self, updated_settings: GlobalSettings, actor: str = "settings_full_update") -> bool:
        """전역 설정을 서버에 업데이트합니다."""
        try:
            response = requests.put(
                f"{self.base_url}/settings",
                json=updated_settings.to_dict(),
                headers={"X-HH-Beholder-Actor": actor, "X-HH-Beholder-Operation": "settings_update"},
                timeout=10,
            )
            self._raise_for_status(response)

            # 서버로부터 최종적으로 저장된 데이터를 응답으로 받습니다.
            saved_settings_data = response.json()

            # 서버가 보내준 최신 데이터로 내부 상태를 갱신합니다.
            self.global_settings = GlobalSettings.from_dict(saved_settings_data)

            return True
        except requests.RequestException as e:
            print(f"전역 설정 업데이트에 실패했습니다: {e}")
            return False # 실패 시 False 반환

    # --- ProcessSession 관련 메서드 ---

    def start_session(self, process_id: str, process_name: str, start_timestamp: float) -> Optional[ProcessSession]:
        """새로운 프로세스 세션 시작"""
        try:
            data = {
                "process_id": process_id,
                "process_name": process_name,
                "start_timestamp": start_timestamp,
                "runtime_evidence": {
                    "current_process_running": True,
                    "app_instance_id": self.app_instance_id,
                },
            }
            response = requests.post(
                f"{self.base_url}/sessions",
                json=data,
                headers={"X-HH-Beholder-Actor": "process_monitor", "X-HH-Beholder-Operation": "runtime_start"},
                timeout=10,
            )
            self._raise_for_status(response)
            return ProcessSession.from_dict(response.json())
        except requests.RequestException as e:
            print(f"세션 시작 실패: {e}")
            return None

    def end_session(self, session_id: int, end_timestamp: float, stamina_at_end: Optional[int] = None) -> Optional[ProcessSession]:
        """프로세스 세션 종료"""
        try:
            data = {
                "end_timestamp": end_timestamp,
                "session_duration": 0  # 서버에서 자동 계산됨
            }
            if stamina_at_end is not None:
                data["stamina_at_end"] = stamina_at_end
            response = requests.put(
                f"{self.base_url}/sessions/{session_id}/end",
                json=data,
                headers={"X-HH-Beholder-Actor": "process_monitor", "X-HH-Beholder-Operation": "runtime_stop"},
                timeout=10
            )
            self._raise_for_status(response)
            return ProcessSession.from_dict(response.json())
        except requests.RequestException as e:
            print(f"세션 종료 실패: {e}")
            return None

    def get_active_session(self, process_id: str) -> Optional[ProcessSession]:
        """특정 프로세스의 현재 활성 세션 조회"""
        try:
            response = requests.get(f"{self.base_url}/sessions/process/{process_id}/active", timeout=10)
            self._raise_for_status(response)
            data = response.json()
            return ProcessSession.from_dict(data) if data else None
        except requests.RequestException as e:
            print(f"활성 세션 조회 실패: {e}")
            return None

    def get_sessions_by_process(self, process_id: str, skip: int = 0, limit: int = 100) -> List[ProcessSession]:
        """특정 프로세스의 세션 이력 조회"""
        try:
            response = requests.get(
                f"{self.base_url}/sessions/process/{process_id}",
                params={"skip": skip, "limit": limit},
                timeout=10
            )
            self._raise_for_status(response)
            sessions_data = response.json()
            return [ProcessSession.from_dict(s) for s in sessions_data]
        except requests.RequestException as e:
            print(f"세션 이력 조회 실패: {e}")
            return []

    def get_all_sessions(self, skip: int = 0, limit: int = 100) -> List[ProcessSession]:
        """모든 세션 조회"""
        try:
            response = requests.get(
                f"{self.base_url}/sessions",
                params={"skip": skip, "limit": limit},
                timeout=10
            )
            self._raise_for_status(response)
            sessions_data = response.json()
            return [ProcessSession.from_dict(s) for s in sessions_data]
        except requests.RequestException as e:
            print(f"전체 세션 조회 실패: {e}")
            return []

    def get_last_session(self, process_id: str) -> Optional[ProcessSession]:
        """특정 프로세스의 가장 최근 완료된 세션 조회"""
        try:
            response = requests.get(f"{self.base_url}/sessions/process/{process_id}/last", timeout=10)
            if response.status_code == 404:
                return None
            self._raise_for_status(response)
            return ProcessSession.from_dict(response.json())
        except requests.RequestException as e:
            print(f"마지막 세션 조회 실패: {e}")
            return None

    def update_session_stamina(self, session_id: int, stamina_at_end: int) -> bool:
        """세션의 종료 스태미나 값을 업데이트합니다."""
        try:
            response = requests.patch(
                f"{self.base_url}/sessions/{session_id}/stamina",
                params={"stamina_at_end": stamina_at_end},
                headers={"X-HH-Beholder-Actor": "hoyolab_slow_followup", "X-HH-Beholder-Operation": "hoyolab_session_stamina_rewrite"},
                timeout=10
            )
            self._raise_for_status(response)
            return True
        except requests.RequestException as e:
            print(f"세션 스태미나 업데이트 실패: {e}")
            return False
