# data_models.py
import datetime
import uuid # 프로세스 ID 생성을 위해 추가
from typing import List, Optional, Dict, Any

class ManagedProcess:
    def __init__(self,
                 name: str,
                 monitoring_path: str,
                 launch_path: str,
                 id: Optional[str] = None, # ID는 내부적으로 생성
                 server_reset_time_str: Optional[str] = None, # "HH:MM"
                 user_cycle_hours: Optional[int] = 24, # 기본값 24시간
                 mandatory_times_str: Optional[List[str]] = None,
                 is_mandatory_time_enabled: bool = False,
                 last_played_timestamp: Optional[float] = None, # Unix timestamp
                 original_launch_path: Optional[str] = None): # 원본 실행 경로 보존
        
        self.id = id if id else str(uuid.uuid4()) # ID가 없으면 새로 생성
        self.name = name
        self.monitoring_path = monitoring_path
        self.launch_path = launch_path
        
        self.server_reset_time_str = server_reset_time_str
        self.user_cycle_hours = user_cycle_hours
        self.mandatory_times_str = mandatory_times_str if mandatory_times_str else []
        self.is_mandatory_time_enabled = is_mandatory_time_enabled
        
        self.last_played_timestamp = last_played_timestamp
        self.original_launch_path = original_launch_path if original_launch_path else launch_path

    def __repr__(self):
        return f"<ManagedProcess(id='{self.id}', name='{self.name}')>"

    def to_dict(self) -> Dict:
        """JSON 저장을 위해 객체를 딕셔너리로 변환합니다."""
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: Dict) -> 'ManagedProcess':
        """딕셔너리에서 객체를 생성합니다 (JSON 로드 시 사용)."""
        # 이전 버전과의 호환성을 위해 original_launch_path가 없을 경우 launch_path로 설정
        if 'original_launch_path' not in data and 'launch_path' in data:
            data['original_launch_path'] = data['launch_path']
        return cls(**data)

class GlobalSettings:
    def __init__(self,
                 sleep_start_time_str: str = "00:00",
                 sleep_end_time_str: str = "08:00",
                 sleep_correction_advance_notify_hours: float = 1.0,
                 cycle_deadline_advance_notify_hours: float = 2.0,
                 run_on_startup: bool = False,
                 lock_window_resize: bool = False,
                 always_on_top: bool = False,
                 run_as_admin: bool = False,
                 notify_on_launch_success: bool = True,
                 notify_on_launch_failure: bool = True,
                 notify_on_mandatory_time: bool = True,
                 notify_on_cycle_deadline: bool = True,
                 notify_on_sleep_correction: bool = True,
                 notify_on_daily_reset: bool = True): # 알림 설정 옵션 추가
        
        self.sleep_start_time_str = sleep_start_time_str
        self.sleep_end_time_str = sleep_end_time_str
        self.sleep_correction_advance_notify_hours = sleep_correction_advance_notify_hours
        self.cycle_deadline_advance_notify_hours = cycle_deadline_advance_notify_hours
        self.run_on_startup = run_on_startup
        self.lock_window_resize = lock_window_resize
        self.always_on_top = always_on_top
        self.run_as_admin = run_as_admin # <<< 새 속성 초기화
        # 알림 옵션
        self.notify_on_launch_success = notify_on_launch_success
        self.notify_on_launch_failure = notify_on_launch_failure
        self.notify_on_mandatory_time = notify_on_mandatory_time
        self.notify_on_cycle_deadline = notify_on_cycle_deadline
        self.notify_on_sleep_correction = notify_on_sleep_correction
        self.notify_on_daily_reset = notify_on_daily_reset

    def to_dict(self) -> Dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: Dict) -> 'GlobalSettings':
        # 이전 버전과의 호환성을 위해 run_on_startup이 없을 경우 기본값 False 사용
        if 'run_on_startup' not in data:
            data['run_on_startup'] = False
        # 이전 버전과의 호환성을 위해 lock_window_resize가 없을 경우 기본값 False 사용
        if 'lock_window_resize' not in data:
            data['lock_window_resize'] = False
        # 이전 버전과의 호환성을 위해 always_on_top이 없을 경우 기본값 False 사용
        if 'always_on_top' not in data:
            data['always_on_top'] = False
        # 이전 버전과의 호환성을 위해 run_as_admin이 없을 경우 기본값 False 사용
        if 'run_as_admin' not in data:
            data['run_as_admin'] = False
        # 알림 옵션들 역호환 기본값 추가
        if 'notify_on_launch_success' not in data:
            data['notify_on_launch_success'] = True
        if 'notify_on_launch_failure' not in data:
            data['notify_on_launch_failure'] = True
        if 'notify_on_mandatory_time' not in data:
            data['notify_on_mandatory_time'] = True
        if 'notify_on_cycle_deadline' not in data:
            data['notify_on_cycle_deadline'] = True
        if 'notify_on_sleep_correction' not in data:
            data['notify_on_sleep_correction'] = True
        if 'notify_on_daily_reset' not in data:
            data['notify_on_daily_reset'] = True
        return cls(**data)
    
class WebShortcut:
    """ 사용자가 추가하는 웹 바로 가기 버튼의 정보를 담는 클래스 """
    def __init__(self,
                 id: Optional[str] = None,
                 name: str = "",
                 url: str = "",
                 refresh_time_str: Optional[str] = None, # HH:MM 형식, 예: "10:00"
                 last_reset_timestamp: Optional[float] = None 
                ):
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.url = url
        self.refresh_time_str = refresh_time_str
        self.last_reset_timestamp = last_reset_timestamp

    def __repr__(self):
        return (f"WebShortcut(id='{self.id}', name='{self.name}', url='{self.url}', "
                f"refresh_time_str='{self.refresh_time_str}', last_reset_timestamp={self.last_reset_timestamp})")

    def to_dict(self) -> Dict[str, Any]:
        """ 객체를 직렬화 가능한 딕셔너리로 변환합니다. """
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "refresh_time_str": self.refresh_time_str,
            "last_reset_timestamp": self.last_reset_timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WebShortcut':
        """ 딕셔너리에서 객체를 생성합니다. """
        # 이전 버전과의 호환성을 위해 refresh_cycle_hours는 무시합니다.
        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            url=data.get("url", ""),
            refresh_time_str=data.get("refresh_time_str"), # None일 수 있음
            last_reset_timestamp=data.get("last_reset_timestamp"), # None일 수 있음
        )