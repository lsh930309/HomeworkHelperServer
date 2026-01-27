from pydantic import BaseModel
from typing import List, Optional

class ProcessSchema(BaseModel):
    id: Optional[str] = None
    name: str
    monitoring_path: str
    launch_path: str
    server_reset_time_str: Optional[str] = None
    user_cycle_hours: Optional[int] = 24
    mandatory_times_str: Optional[List[str]] = None
    is_mandatory_time_enabled: bool = False
    last_played_timestamp: Optional[float] = None
    original_launch_path: Optional[str] = None
    preferred_launch_type: str = "shortcut"
    user_preset_id: Optional[str] = None
    # HoYoLab 스태미나 필드
    stamina_tracking_enabled: bool = False
    hoyolab_game_id: Optional[str] = None
    stamina_current: Optional[int] = None
    stamina_max: Optional[int] = None
    stamina_updated_at: Optional[float] = None

    class Config:
        from_attributes = True

class ProcessCreateSchema(BaseModel):
    id: Optional[str] = None
    name: str
    monitoring_path: str
    launch_path: str
    server_reset_time_str: Optional[str] = None
    user_cycle_hours: Optional[int] = 24
    mandatory_times_str: Optional[List[str]] = None
    is_mandatory_time_enabled: bool = False
    last_played_timestamp: Optional[float] = None
    original_launch_path: Optional[str] = None
    preferred_launch_type: str = "shortcut"
    user_preset_id: Optional[str] = None
    # HoYoLab 스태미나 필드
    stamina_tracking_enabled: bool = False
    hoyolab_game_id: Optional[str] = None
    stamina_current: Optional[int] = None
    stamina_max: Optional[int] = None
    stamina_updated_at: Optional[float] = None

class WebShortcutBase(BaseModel):
    name: str = ""
    url: str = ""
    refresh_time_str: Optional[str] = None
    last_reset_timestamp: Optional[float] = None

class WebShortcutCreate(WebShortcutBase):
    id: Optional[str] = None

class WebShortcutSchema(WebShortcutBase):
    id: str

    class Config:
        from_attributes = True

class GlobalSettingsSchema(BaseModel):
    sleep_start_time_str: str = "00:00"
    sleep_end_time_str: str = "08:00"
    sleep_correction_advance_notify_hours: float = 1.0
    cycle_deadline_advance_notify_hours: float = 2.0
    run_on_startup: bool = False
    always_on_top: bool = False
    run_as_admin: bool = False
    notify_on_launch_success: bool = True
    notify_on_launch_failure: bool = True
    notify_on_mandatory_time: bool = True
    notify_on_cycle_deadline: bool = True
    notify_on_sleep_correction: bool = True
    notify_on_daily_reset: bool = True
    # 스태미나 알림 설정
    stamina_notify_enabled: bool = True
    stamina_notify_threshold: int = 20


class ProcessSessionCreate(BaseModel):
    """세션 생성용 스키마"""
    process_id: str
    process_name: str
    start_timestamp: float
    user_preset_id: Optional[str] = None  # 사용자 설정 프리셋 ID


class ProcessSessionUpdate(BaseModel):
    """세션 종료 업데이트용 스키마"""
    end_timestamp: float
    session_duration: float
    stamina_at_end: Optional[int] = None  # 종료 시점 스태미나


class ProcessSessionSchema(BaseModel):
    """세션 조회용 스키마"""
    id: int
    process_id: str
    process_name: str
    start_timestamp: float
    end_timestamp: Optional[float] = None
    session_duration: Optional[float] = None
    user_preset_id: Optional[str] = None  # 사용자 설정 프리셋 ID
    stamina_at_end: Optional[int] = None  # 종료 시점 스태미나

    class Config:
        from_attributes = True