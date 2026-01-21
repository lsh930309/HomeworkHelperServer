# data_models.py
import datetime
import time
import uuid # 프로세스 ID 생성을 위해 추가
from typing import List, Optional, Dict, Any, Tuple

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
                 original_launch_path: Optional[str] = None, # 원본 실행 경로 보존
                 # 실행 방식 선택: "auto" (기본), "shortcut" (바로가기 우선), "direct" (직접 실행 우선)
                 preferred_launch_type: str = "shortcut",
                 # MVP 연동 필드
                 game_schema_id: Optional[str] = None,  # 게임 스키마 ID (예: "zenless_zone_zero")
                 mvp_enabled: bool = False,             # MVP 기능 활성화 여부
                 # HoYoLab 스태미나 연동 필드
                 stamina_current: Optional[int] = None,
                 stamina_max: Optional[int] = None,
                 stamina_updated_at: Optional[float] = None):

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
        
        # 실행 방식 선택 (auto, shortcut, direct)
        self.preferred_launch_type = preferred_launch_type

        # MVP 연동 필드 초기화
        self.game_schema_id = game_schema_id
        self.mvp_enabled = mvp_enabled
        
        # HoYoLab 스태미나 연동 필드 초기화
        self.stamina_current = stamina_current
        self.stamina_max = stamina_max
        self.stamina_updated_at = stamina_updated_at

    def __repr__(self):
        return f"<ManagedProcess(id='{self.id}', name='{self.name}', schema='{self.game_schema_id}')>"

    def to_dict(self) -> Dict:
        """JSON 저장을 위해 객체를 딕셔너리로 변환합니다."""
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: Dict) -> 'ManagedProcess':
        """딕셔너리에서 객체를 생성합니다 (JSON 로드 시 사용)."""
        # 이전 버전과의 호환성을 위해 original_launch_path가 없을 경우 launch_path로 설정
        if 'original_launch_path' not in data and 'launch_path' in data:
            data['original_launch_path'] = data['launch_path']
        # 실행 방식 선택 하위 호환성
        if 'preferred_launch_type' not in data:
            data['preferred_launch_type'] = 'shortcut'
        # MVP 연동 필드 하위 호환성
        if 'game_schema_id' not in data:
            data['game_schema_id'] = None
        if 'mvp_enabled' not in data:
            data['mvp_enabled'] = False
        # 스태미나 필드 하위 호환성
        if 'stamina_current' not in data:
            data['stamina_current'] = None
        if 'stamina_max' not in data:
            data['stamina_max'] = None
        if 'stamina_updated_at' not in data:
            data['stamina_updated_at'] = None
        return cls(**data)
    
    def is_hoyoverse_game(self) -> bool:
        """호요버스 게임인지 확인"""
        return self.game_schema_id in ("honkai_starrail", "zenless_zone_zero")
    
    def get_predicted_stamina(self) -> Optional[Tuple[int, int]]:
        """현재 시점의 예측 스태미나와 최대치를 반환.
        
        6분에 1씩 회복되는 것을 기준으로 로컬 연산합니다.
        
        Returns:
            (predicted_current, max_stamina) 또는 스태미나 정보가 없으면 None
        """
        if self.stamina_current is None or self.stamina_max is None:
            return None
        
        if self.stamina_updated_at is None:
            return (self.stamina_current, self.stamina_max)
        
        # 6분에 1씩 회복
        elapsed_seconds = time.time() - self.stamina_updated_at
        recovered = int(elapsed_seconds / 360)  # 360초 = 6분
        predicted = min(self.stamina_current + recovered, self.stamina_max)
        
        return (predicted, self.stamina_max)
    
    def get_stamina_percentage(self) -> Optional[float]:
        """스태미나 백분율 반환 (0.0 ~ 100.0)"""
        stamina_info = self.get_predicted_stamina()
        if stamina_info is None or stamina_info[1] == 0:
            return None
        predicted, max_stamina = stamina_info
        return (predicted / max_stamina) * 100

class GlobalSettings:
    def __init__(self,
                 sleep_start_time_str: str = "00:00",
                 sleep_end_time_str: str = "08:00",
                 sleep_correction_advance_notify_hours: float = 1.0,
                 cycle_deadline_advance_notify_hours: float = 2.0,
                 run_on_startup: bool = False,
                 always_on_top: bool = False,
                 run_as_admin: bool = False,
                 notify_on_launch_success: bool = True,
                 notify_on_launch_failure: bool = True,
                 notify_on_mandatory_time: bool = True,
                 notify_on_cycle_deadline: bool = True,
                 notify_on_sleep_correction: bool = True,
                 notify_on_daily_reset: bool = True,
                 # 스태미나 알림 설정 (호요버스 게임)
                 stamina_notify_enabled: bool = True,
                 stamina_notify_threshold: int = 20):  # 최대 - N 이상일 때 알림
        
        self.sleep_start_time_str = sleep_start_time_str
        self.sleep_end_time_str = sleep_end_time_str
        self.sleep_correction_advance_notify_hours = sleep_correction_advance_notify_hours
        self.cycle_deadline_advance_notify_hours = cycle_deadline_advance_notify_hours
        self.run_on_startup = run_on_startup
        self.always_on_top = always_on_top
        self.run_as_admin = run_as_admin # <<< 새 속성 초기화
        # 알림 옵션
        self.notify_on_launch_success = notify_on_launch_success
        self.notify_on_launch_failure = notify_on_launch_failure
        self.notify_on_mandatory_time = notify_on_mandatory_time
        self.notify_on_cycle_deadline = notify_on_cycle_deadline
        self.notify_on_sleep_correction = notify_on_sleep_correction
        self.notify_on_daily_reset = notify_on_daily_reset
        # 스태미나 알림 설정
        self.stamina_notify_enabled = stamina_notify_enabled
        self.stamina_notify_threshold = stamina_notify_threshold

    def to_dict(self) -> Dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: Dict) -> 'GlobalSettings':
        # 이전 버전과의 호환성을 위해 run_on_startup이 없을 경우 기본값 False 사용
        if 'run_on_startup' not in data:
            data['run_on_startup'] = False
        # 이전 버전의 lock_window_resize 필드는 제거됨 (무시)
        if 'lock_window_resize' in data:
            del data['lock_window_resize']
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
        # 스태미나 알림 설정 하위 호환성
        if 'stamina_notify_enabled' not in data:
            data['stamina_notify_enabled'] = True
        if 'stamina_notify_threshold' not in data:
            data['stamina_notify_threshold'] = 20
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


class ProcessSession:
    """프로세스 세션 데이터 모델 (API 클라이언트용)"""
    def __init__(self,
                 id: Optional[int] = None,
                 process_id: str = "",
                 process_name: str = "",
                 start_timestamp: float = 0.0,
                 end_timestamp: Optional[float] = None,
                 session_duration: Optional[float] = None):
        self.id = id
        self.process_id = process_id
        self.process_name = process_name
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.session_duration = session_duration

    def __repr__(self):
        return (f"ProcessSession(id={self.id}, process_name='{self.process_name}', "
                f"start={self.start_timestamp}, end={self.end_timestamp}, duration={self.session_duration})")

    def to_dict(self) -> Dict[str, Any]:
        """객체를 직렬화 가능한 딕셔너리로 변환"""
        return {
            "id": self.id,
            "process_id": self.process_id,
            "process_name": self.process_name,
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "session_duration": self.session_duration,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProcessSession':
        """딕셔너리에서 객체를 생성"""
        return cls(
            id=data.get("id"),
            process_id=data.get("process_id", ""),
            process_name=data.get("process_name", ""),
            start_timestamp=data.get("start_timestamp", 0.0),
            end_timestamp=data.get("end_timestamp"),
            session_duration=data.get("session_duration"),
        )