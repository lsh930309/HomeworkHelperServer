import requests
from typing import List, Optional, Dict, Any

# 서버가 로컬호스트 8000번 포트에서 실행된다고 가정합니다.
BASE_URL = "http://127.0.0.1:8000"

class ApiClient:
    """
    FastAPI 서버와 상호작용하여 기존 DataManager를 대체하는 클라이언트입니다.
    """

    def get_processes(self) -> List[Dict[str, Any]]:
        """서버에서 모든 관리 대상 프로세스 목록을 가져옵니다."""
        try:
            response = requests.get(f"{BASE_URL}/processes")
            response.raise_for_status()  # 오류 상태 코드 발생 시 예외 처리
            return response.json()
        except requests.RequestException as e:
            print(f"프로세스 목록 가져오기 오류: {e}")
            return []

    def get_process_by_id(self, process_id: str) -> Optional[Dict[str, Any]]:
        """ID로 단일 프로세스 정보를 가져옵니다."""
        try:
            response = requests.get(f"{BASE_URL}/processes/{process_id}")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"프로세스 정보 가져오기 오류 (ID: {process_id}): {e}")
            return None

    def create_process(self, process_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """새로운 프로세스를 생성합니다."""
        try:
            # Pydantic 스키마에 맞게 일부 필드 조정
            # ProcessCreateSchema는 id, last_played_timestamp 등을 받지 않음
            create_data = {
                "name": process_data.get("name"),
                "monitoring_path": process_data.get("monitoring_path"),
                "launch_path": process_data.get("launch_path"),
                "server_reset_time_str": process_data.get("server_reset_time_str"),
                "user_cycle_hours": process_data.get("user_cycle_hours"),
                "mandatory_times_str": process_data.get("mandatory_times_str"),
                "is_mandatory_time_enabled": process_data.get("is_mandatory_time_enabled"),
            }
            response = requests.post(f"{BASE_URL}/processes", json=create_data)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"프로세스 생성 오류: {e}")
            return None

    def update_process(self, process_id: str, process_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """기존 프로세스 정보를 업데이트합니다."""
        try:
            response = requests.put(f"{BASE_URL}/processes/{process_id}", json=process_data)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"프로세스 업데이트 오류 (ID: {process_id}): {e}")
            return None

    def delete_process(self, process_id: str) -> bool:
        """프로세스를 삭제합니다."""
        try:
            response = requests.delete(f"{BASE_URL}/processes/{process_id}")
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"프로세스 삭제 오류 (ID: {process_id}): {e}")
            return False

    def get_settings(self) -> Optional[Dict[str, Any]]:
        """전역 설정을 가져옵니다."""
        try:
            response = requests.get(f"{BASE_URL}/settings")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"설정 가져오기 오류: {e}")
            # 앱 충돌을 방지하기 위해 실패 시 기본 구조 반환
            return {
                "sleep_start_time_str": "00:00", "sleep_end_time_str": "08:00",
                "sleep_correction_advance_notify_hours": 1.0, "cycle_deadline_advance_notify_hours": 2.0,
                "run_on_startup": False, "lock_window_resize": False, "always_on_top": False,
                "run_as_admin": False, "notify_on_launch_success": True, "notify_on_launch_failure": True,
                "notify_on_mandatory_time": True, "notify_on_cycle_deadline": True,
                "notify_on_sleep_correction": True, "notify_on_daily_reset": True
            }

    def update_settings(self, settings_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """전역 설정을 업데이트합니다."""
        try:
            response = requests.put(f"{BASE_URL}/settings", json=settings_data)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"설정 업데이트 오류: {e}")
            return None

    # WebShortcut 관련 메소드들
    def get_shortcuts(self) -> List[Dict[str, Any]]:
        """서버에서 모든 웹 바로가기 목록을 가져옵니다."""
        try:
            response = requests.get(f"{BASE_URL}/shortcuts")
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"웹 바로가기 목록 가져오기 오류: {e}")
            return []

    def create_shortcut(self, shortcut_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """새로운 웹 바로가기를 생성합니다."""
        try:
            response = requests.post(f"{BASE_URL}/shortcuts", json=shortcut_data)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"웹 바로가기 생성 오류: {e}")
            return None

    def update_shortcut(self, shortcut_id: str, shortcut_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """기존 웹 바로가기를 업데이트합니다."""
        try:
            response = requests.put(f"{BASE_URL}/shortcuts/{shortcut_id}", json=shortcut_data)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"웹 바로가기 업데이트 오류 (ID: {shortcut_id}): {e}")
            return None

    def delete_shortcut(self, shortcut_id: str) -> bool:
        """웹 바로가기를 삭제합니다."""
        try:
            response = requests.delete(f"{BASE_URL}/shortcuts/{shortcut_id}")
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"웹 바로가기 삭제 오류 (ID: {shortcut_id}): {e}")
            return False
