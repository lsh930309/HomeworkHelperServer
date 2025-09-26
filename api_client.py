# api_client.py

import requests
from typing import List, Optional
from data_models import ManagedProcess, WebShortcut, GlobalSettings

class ApiClient:
    """
    FastAPI 서버와 통신하여 데이터를 CRUD하는 클라이언트.
    기존 DataManager의 역할을 대체합니다.
    """
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url
        # 최초 실행 시, 서버에서 모든 데이터를 가져와 내부 변수에 저장합니다.
        self.managed_processes: List[ManagedProcess] = self._fetch_all_processes()
        self.web_shortcuts: List[WebShortcut] = self._fetch_all_web_shortcuts()
        self.global_settings: GlobalSettings = self._fetch_global_settings()
        
    # --- ManagedProcess 관련 메서드 ---
    
    def _fetch_all_processes(self) -> List[ManagedProcess]:
        """서버에서 모든 프로세스 목록을 가져옵니다."""
        try:
            response = requests.get(f"{self.base_url}/processes")
            response.raise_for_status()  # 200번대 상태 코드가 아니면 에러 발생
            processes_data = response.json()
            # JSON 딕셔너리 리스트를 ManagedProcess 객체 리스트로 변환
            return [ManagedProcess.from_dict(p) for p in processes_data]
        except requests.RequestException as e:
            print(f"프로세스 목록을 불러오는 데 실패했습니다: {e}")
            return []

    def get_process_by_id(self, process_id: str) -> Optional[ManagedProcess]:
        """ID로 단일 프로세스를 찾습니다 (내부 메모리에서)."""
        for p in self.managed_processes:
            if p.id == process_id:
                return p
        return None

    def add_process(self, process: ManagedProcess) -> bool:
        """새로운 프로세스를 서버에 추가합니다."""
        try:
            # Pydantic 스키마에 맞게 id를 제외하고 데이터를 보냅니다.
            data_to_send = process.to_dict()
            if 'id' in data_to_send:
                del data_to_send['id']

            response = requests.post(f"{self.base_url}/processes", json=data_to_send)
            response.raise_for_status()
            
            # 성공 시, 내부 데이터 목록도 새로고침합니다.
            new_process_data = response.json()
            new_process_obj = ManagedProcess.from_dict(new_process_data)

            self.managed_processes.append(new_process_obj)
            return True
        except requests.RequestException as e:
            print(f"프로세스 추가에 실패했습니다: {e}")
            return False

    def remove_process(self, process_id: str) -> bool:
        """ID로 프로세스를 서버에서 삭제합니다."""
        try:
            response = requests.delete(f"{self.base_url}/processes/{process_id}")
            response.raise_for_status()
            
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

            response = requests.put(f"{self.base_url}/processes/{updated_process.id}", json=data_to_send)
            response.raise_for_status()
            
            self.managed_processes = self._fetch_all_processes()
            return True
        except requests.RequestException as e:
            print(f"프로세스 업데이트에 실패했습니다: {e}")
            return False
            
    # --- WebShortcut 관련 메서드 ---

    def _fetch_all_web_shortcuts(self) -> List[WebShortcut]:
        """서버에서 모든 웹 바로 가기 목록을 가져옵니다."""
        try:
            response = requests.get(f"{self.base_url}/shortcuts")
            response.raise_for_status()
            shortcuts_data = response.json()
            return [WebShortcut.from_dict(sc) for sc in shortcuts_data]
        except requests.RequestException as e:
            print(f"웹 바로 가기 목록을 불러오는 데 실패했습니다: {e}")
            return []
        
    def get_web_shortcut_by_id(self, shortcut_id: str) -> Optional[WebShortcut]:
        """ID로 단일 웹 바로 가기를 찾습니다 (내부 메모리에서)."""
        for sc in self.web_shortcuts:
            if sc.id == shortcut_id:
                return sc
        return None

    def add_web_shortcut(self, shortcut: WebShortcut) -> bool:
        """새로운 웹 바로 가기를 서버에 추가합니다."""
        try:
            data_to_send = shortcut.to_dict()
            if 'id' in data_to_send:
                del data_to_send['id']

            response = requests.post(f"{self.base_url}/shortcuts", json=data_to_send)
            response.raise_for_status()
            
            self.web_shortcuts = self._fetch_all_web_shortcuts()
            return True
        except requests.RequestException as e:
            print(f"웹 바로 가기 추가에 실패했습니다: {e}")
            return False

    def remove_web_shortcut(self, shortcut_id: str) -> bool:
        """ID로 웹 바로 가기를 서버에서 삭제합니다."""
        try:
            response = requests.delete(f"{self.base_url}/shortcuts/{shortcut_id}")
            response.raise_for_status()
            
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

            response = requests.put(f"{self.base_url}/shortcuts/{updated_shortcut.id}", json=data_to_send)
            response.raise_for_status()
            
            self.web_shortcuts = self._fetch_all_web_shortcuts()
            return True
        except requests.RequestException as e:
            print(f"웹 바로 가기 업데이트에 실패했습니다: {e}")
            return False
        
    # --- GlobalSettings 관련 메서드 ---

    def _fetch_global_settings(self) -> GlobalSettings:
        """서버에서 전역 설정을 가져옵니다."""
        try:
            response = requests.get(f"{self.base_url}/settings")
            response.raise_for_status()
            return GlobalSettings.from_dict(response.json())
        except requests.RequestException as e:
            print(f"전역 설정을 불러오는 데 실패했습니다: {e}")
            return GlobalSettings()
        
    def save_global_settings(self, updated_settings: GlobalSettings) -> bool:
        """전역 설정을 서버에 업데이트합니다."""
        try:
            response = requests.put(f"{self.base_url}/settings", json=updated_settings.to_dict())
            response.raise_for_status()
            
            # 서버로부터 최종적으로 저장된 데이터를 응답으로 받습니다.
            saved_settings_data = response.json()
            
            # 서버가 보내준 최신 데이터로 내부 상태를 갱신합니다.
            self.global_settings = GlobalSettings.from_dict(saved_settings_data)
            
            return True
        except requests.RequestException as e:
            print(f"전역 설정 업데이트에 실패했습니다: {e}")
            return False # 실패 시 False 반환