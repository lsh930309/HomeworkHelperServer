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
                 # 사용자 설정 프리셋 ID
                 user_preset_id: Optional[str] = None,  # 사용자 설정 프리셋 ID (예: "zenless_zone_zero")
                 # HoYoLab 스태미나 연동 필드
                 stamina_tracking_enabled: bool = False, # 스태미나 자동 추적 활성화
                 hoyolab_game_id: Optional[str] = None,  # 추적할 호요버스 게임 ID
                 stamina_current: Optional[int] = None,
                 stamina_max: Optional[int] = None,
                 stamina_updated_at: Optional[float] = None,
                 # 앱 볼륨 제어
                 default_volume: Optional[int] = None,
                 default_muted: bool = False):
        """관리 대상 프로세스 인스턴스를 초기화합니다."""
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

        # 사용자 설정 프리셋 ID
        self.user_preset_id = user_preset_id

        # HoYoLab 스태미나 연동 필드 초기화
        self.stamina_tracking_enabled = stamina_tracking_enabled
        self.hoyolab_game_id = hoyolab_game_id
        self.stamina_current = stamina_current
        self.stamina_max = stamina_max
        self.stamina_updated_at = stamina_updated_at

        # 앱 볼륨 제어
        self.default_volume = default_volume
        self.default_muted = default_muted

    def __repr__(self):
        """ManagedProcess 객체의 문자열 표현을 반환합니다."""
        return f"<ManagedProcess(id='{self.id}', name='{self.name}', preset='{self.user_preset_id}')>"

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
        # 사용자 프리셋 ID 하위 호환성 (game_schema_id → user_preset_id 마이그레이션)
        if 'user_preset_id' not in data:
            data['user_preset_id'] = data.get('game_schema_id')  # 기존 game_schema_id 값 복사
        # 스태미나 필드 하위 호환성
        if 'stamina_tracking_enabled' not in data:
            data['stamina_tracking_enabled'] = False
        if 'hoyolab_game_id' not in data:
            data['hoyolab_game_id'] = None
        if 'stamina_current' not in data:
            data['stamina_current'] = None
        if 'stamina_max' not in data:
            data['stamina_max'] = None
        if 'stamina_updated_at' not in data:
            data['stamina_updated_at'] = None
        # 볼륨 필드 하위 호환성
        if 'default_volume' not in data:
            data['default_volume'] = None
        if 'default_muted' not in data:
            data['default_muted'] = False
        return cls(**data)
    
    def is_hoyoverse_game(self) -> bool:
        """호요버스 게임 스태미나 추적이 활성화되어 있는지 확인"""
        return self.stamina_tracking_enabled and self.hoyolab_game_id is not None
    
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
                 notify_on_mandatory_time: bool = True,
                 notify_on_cycle_deadline: bool = True,
                 notify_on_sleep_correction: bool = True,
                 notify_on_daily_reset: bool = True,
                 # 스태미나 알림 설정 (호요버스 게임)
                 stamina_notify_enabled: bool = True,
                 stamina_notify_threshold: int = 20,  # 최대 - N 이상일 때 알림
                 # 테마 설정
                 theme: str = "system",  # "system" | "light" | "dark"
                 # 게임 실행 시 창 숨기기
                 hide_on_game: bool = True,
                 # 사이드바 설정
                 sidebar_enabled: bool = True,
                 sidebar_trigger_y_start: float = 0.1,
                 sidebar_trigger_y_end: float = 0.9,
                 sidebar_auto_hide_ms: int = 3000,
                 sidebar_edge_width_px: int = 2,
                 sidebar_effect: str = "acrylic",
                 sidebar_height_ratio: float = 1.0,
                 sidebar_opacity: float = 0.85,
                 sidebar_clock_enabled: bool = True,
                 sidebar_clock_format: str = "%H:%M:%S",
                 sidebar_playtime_enabled: bool = True,
                 sidebar_playtime_prefix: str = "오늘 플레이 시간",
                 sidebar_volume_section_enabled: bool = True,
                 # 스크린샷 설정
                 screenshot_enabled: bool = True,
                 screenshot_save_dir: str = "",
                 screenshot_gamepad_trigger: bool = True,
                 screenshot_disable_gamebar: bool = False,
                 screenshot_capture_mode: str = "fullscreen",
                 screenshot_gamepad_button_index: int = -1):
        """전역 설정 인스턴스를 초기화합니다."""
        self.sleep_start_time_str = sleep_start_time_str
        self.sleep_end_time_str = sleep_end_time_str
        self.sleep_correction_advance_notify_hours = sleep_correction_advance_notify_hours
        self.cycle_deadline_advance_notify_hours = cycle_deadline_advance_notify_hours
        self.run_on_startup = run_on_startup
        self.always_on_top = always_on_top
        self.run_as_admin = run_as_admin # <<< 새 속성 초기화
        # 알림 옵션
        self.notify_on_mandatory_time = notify_on_mandatory_time
        self.notify_on_cycle_deadline = notify_on_cycle_deadline
        self.notify_on_sleep_correction = notify_on_sleep_correction
        self.notify_on_daily_reset = notify_on_daily_reset
        # 스태미나 알림 설정
        self.stamina_notify_enabled = stamina_notify_enabled
        self.stamina_notify_threshold = stamina_notify_threshold
        # 테마 / 게임 모드
        self.theme = theme
        self.hide_on_game = hide_on_game
        # 사이드바
        self.sidebar_enabled = sidebar_enabled
        self.sidebar_trigger_y_start = sidebar_trigger_y_start
        self.sidebar_trigger_y_end = sidebar_trigger_y_end
        self.sidebar_auto_hide_ms = sidebar_auto_hide_ms
        self.sidebar_edge_width_px = sidebar_edge_width_px
        self.sidebar_effect = sidebar_effect
        self.sidebar_height_ratio = sidebar_height_ratio
        self.sidebar_opacity = sidebar_opacity
        self.sidebar_clock_enabled = sidebar_clock_enabled
        self.sidebar_clock_format = sidebar_clock_format
        self.sidebar_playtime_enabled = sidebar_playtime_enabled
        self.sidebar_playtime_prefix = sidebar_playtime_prefix
        self.sidebar_volume_section_enabled = sidebar_volume_section_enabled
        # 스크린샷
        self.screenshot_enabled = screenshot_enabled
        self.screenshot_save_dir = screenshot_save_dir
        self.screenshot_gamepad_trigger = screenshot_gamepad_trigger
        self.screenshot_disable_gamebar = screenshot_disable_gamebar
        self.screenshot_capture_mode = screenshot_capture_mode
        self.screenshot_gamepad_button_index = screenshot_gamepad_button_index

    def to_dict(self) -> Dict:
        """JSON 저장을 위해 객체를 딕셔너리로 변환합니다."""
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: Dict) -> 'GlobalSettings':
        """딕셔너리에서 객체를 생성합니다 (이전 버전 호환성 처리 포함)."""
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
        # notify_on_launch_success / notify_on_launch_failure 는 제거됨 — 구버전 DB 값은 무시
        data.pop('notify_on_launch_success', None)
        data.pop('notify_on_launch_failure', None)
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
        # 테마 / 게임 모드 하위 호환성
        if 'theme' not in data:
            data['theme'] = 'system'
        if 'hide_on_game' not in data:
            data['hide_on_game'] = True
        # 사이드바 설정 하위 호환성 + 타입/범위 정규화
        data['sidebar_enabled'] = bool(data.get('sidebar_enabled', True))
        _y_start = max(0.0, min(1.0, float(data.get('sidebar_trigger_y_start', 0.1))))
        _y_end   = max(0.0, min(1.0, float(data.get('sidebar_trigger_y_end',   0.9))))
        data['sidebar_trigger_y_start'] = min(_y_start, _y_end)
        data['sidebar_trigger_y_end']   = max(_y_start, _y_end)
        # sidebar_auto_hide_ms 하위 호환성 (구버전: sidebar_auto_hide_sec)
        if 'sidebar_auto_hide_ms' not in data and 'sidebar_auto_hide_sec' in data:
            data['sidebar_auto_hide_ms'] = max(0, int(data['sidebar_auto_hide_sec'])) * 1000
        else:
            data['sidebar_auto_hide_ms'] = max(0, int(data.get('sidebar_auto_hide_ms', 3000)))
        data.pop('sidebar_auto_hide_sec', None)
        data['sidebar_edge_width_px'] = max(1, min(50, int(data.get('sidebar_edge_width_px', 2))))
        _effect = data.get('sidebar_effect', 'acrylic')
        if _effect not in ('mica', 'acrylic', 'none'):
            _effect = 'acrylic'
        data['sidebar_effect'] = _effect
        data['sidebar_height_ratio'] = max(0.3, min(1.0, float(data.get('sidebar_height_ratio', 1.0))))
        data['sidebar_opacity'] = max(0.1, min(1.0, float(data.get('sidebar_opacity', 0.85))))
        data['sidebar_clock_enabled'] = bool(data.get('sidebar_clock_enabled', True))
        data['sidebar_clock_format'] = str(data.get('sidebar_clock_format', '%H:%M:%S'))
        data['sidebar_playtime_enabled'] = bool(data.get('sidebar_playtime_enabled', True))
        data['sidebar_playtime_prefix'] = str(data.get('sidebar_playtime_prefix', '오늘 플레이 시간'))
        data['sidebar_volume_section_enabled'] = bool(data.get('sidebar_volume_section_enabled', True))
        # 스크린샷 설정 하위 호환성
        data['screenshot_enabled'] = bool(data.get('screenshot_enabled', True))
        data['screenshot_save_dir'] = str(data.get('screenshot_save_dir', ''))
        data['screenshot_gamepad_trigger'] = bool(data.get('screenshot_gamepad_trigger', True))
        data['screenshot_disable_gamebar'] = bool(data.get('screenshot_disable_gamebar', False))
        _cap_mode = data.get('screenshot_capture_mode', 'fullscreen')
        if _cap_mode not in ('fullscreen', 'game_window'):
            _cap_mode = 'fullscreen'
        data['screenshot_capture_mode'] = _cap_mode
        data['screenshot_gamepad_button_index'] = int(data.get('screenshot_gamepad_button_index', -1))
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
        """웹 바로가기 인스턴스를 초기화합니다."""
        self.id = id if id else str(uuid.uuid4())
        self.name = name
        self.url = url
        self.refresh_time_str = refresh_time_str
        self.last_reset_timestamp = last_reset_timestamp

    def __repr__(self):
        """WebShortcut 객체의 문자열 표현을 반환합니다."""
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
                 session_duration: Optional[float] = None,
                 user_preset_id: Optional[str] = None,
                 stamina_at_end: Optional[int] = None):
        """프로세스 세션 인스턴스를 초기화합니다."""
        self.id = id
        self.process_id = process_id
        self.process_name = process_name
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.session_duration = session_duration
        self.user_preset_id = user_preset_id
        self.stamina_at_end = stamina_at_end

    def __repr__(self):
        """ProcessSession 객체의 문자열 표현을 반환합니다."""
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
            "user_preset_id": self.user_preset_id,
            "stamina_at_end": self.stamina_at_end,
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
            user_preset_id=data.get("user_preset_id"),
            stamina_at_end=data.get("stamina_at_end"),
        )