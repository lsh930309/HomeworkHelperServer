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
    # 범용 외부 리소스 필드
    resource_tracking_enabled: bool = False
    resource_provider: Optional[str] = None
    resource_key: Optional[str] = None
    resource_label: Optional[str] = None
    resource_percent: Optional[float] = None
    resource_updated_at: Optional[float] = None
    resource_status: Optional[str] = None
    # 앱 볼륨 제어
    default_volume: Optional[int] = None
    default_muted: bool = False

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
    # 범용 외부 리소스 필드
    resource_tracking_enabled: bool = False
    resource_provider: Optional[str] = None
    resource_key: Optional[str] = None
    resource_label: Optional[str] = None
    resource_percent: Optional[float] = None
    resource_updated_at: Optional[float] = None
    resource_status: Optional[str] = None
    # 앱 볼륨 제어
    default_volume: Optional[int] = None
    default_muted: bool = False

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
    notify_on_mandatory_time: bool = True
    notify_on_cycle_deadline: bool = True
    notify_on_sleep_correction: bool = True
    notify_on_daily_reset: bool = True
    # 스태미나 알림 설정
    stamina_notify_enabled: bool = True
    stamina_notify_threshold: int = 20
    # 테마 / 게임 모드
    theme: str = "system"
    hide_on_game: bool = True
    # 사이드바
    sidebar_enabled: bool = True
    sidebar_mode: str = "game"
    sidebar_trigger_y_start: float = 0.1
    sidebar_trigger_y_end: float = 0.9
    sidebar_handle_auto_hide: bool = True
    sidebar_auto_hide_ms: int = 3000
    sidebar_edge_width_px: int = 2
    sidebar_height_ratio: float = 1.0
    sidebar_opacity: float = 0.85
    sidebar_clock_enabled: bool = True
    sidebar_clock_format: str = "%H:%M:%S"
    sidebar_playtime_enabled: bool = True
    sidebar_playtime_prefix: str = "오늘 플레이 시간"
    sidebar_volume_section_enabled: bool = True
    # 스크린샷 설정
    screenshot_enabled: bool = True
    screenshot_save_dir: str = ""
    screenshot_gamepad_trigger: bool = True
    screenshot_disable_gamebar: bool = False
    screenshot_capture_mode: str = "fullscreen"
    screenshot_gamepad_button_index: int = -1
    screenshot_trigger_vk: int = 0xB2          # 트리거 가상 키 코드 (기본: 미디어 정지)
    # Recording (OBS)
    recording_enabled: bool = False
    obs_host: str = "localhost"
    obs_port: int = 4455
    obs_password: str = ""
    obs_exe_path: str = ""
    obs_auto_launch: bool = False
    obs_launch_hidden: bool = True
    obs_watch_output_dir: bool = True
    obs_recording_output_dir: str = ""
    recording_hold_threshold_ms: int = 800
    # Remote server mode
    remote_server_mode_enabled: bool = False


class ProcessSessionCreate(BaseModel):
    """세션 생성용 스키마"""
    process_id: str
    process_name: str
    start_timestamp: float
    user_preset_id: Optional[str] = None  # 사용자 설정 프리셋 ID
    session_owner: Optional[str] = None
    lease_token: Optional[str] = None
    runtime_evidence: Optional[dict] = None


class ProcessSessionUpdate(BaseModel):
    """세션 종료 업데이트용 스키마"""
    end_timestamp: float
    session_duration: float
    stamina_at_end: Optional[int] = None  # 종료 시점 스태미나
    resource_percent_at_end: Optional[float] = None  # 종료 시점 외부 리소스 백분율
    close_reason: Optional[str] = None


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
    resource_percent_at_end: Optional[float] = None  # 종료 시점 외부 리소스 백분율
    session_status: Optional[str] = None
    session_owner: Optional[str] = None
    heartbeat_timestamp: Optional[float] = None
    lease_token: Optional[str] = None
    close_reason: Optional[str] = None
    guard_flags: Optional[dict] = None

    class Config:
        from_attributes = True

class GamePlatformLinkBase(BaseModel):
    pc_process_id: str
    pc_display_name: Optional[str] = None
    android_package_name: str
    android_launch_intent_uri: Optional[str] = None
    android_store_url: Optional[str] = None
    platform_account_hint: Optional[str] = None
    hoyolab_game_id: Optional[str] = None
    sync_strategy: str = "manual"


class GamePlatformLinkCreate(GamePlatformLinkBase):
    id: Optional[str] = None


class GamePlatformLinkSchema(GamePlatformLinkBase):
    id: str
    created_at: float
    updated_at: float

    class Config:
        from_attributes = True

class MobileGameSessionSchema(BaseModel):
    id: str
    game_link_id: str
    pc_process_id: str
    pc_display_name: Optional[str] = None
    android_package_name: str
    source: str = "manual"
    status: str = "active"
    started_at: float
    ended_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    created_at: float
    updated_at: float

    class Config:
        from_attributes = True


class DailyCheckInSettingSchema(BaseModel):
    process_id: str
    process_name: Optional[str] = None
    user_preset_id: Optional[str] = None
    provider: str
    game_id: str
    game_name: Optional[str] = None
    enabled: bool = False
    last_attempt_at: Optional[float] = None
    last_result: Optional[str] = None
    last_message: Optional[str] = None
    last_period_start: Optional[float] = None
    last_success_at: Optional[float] = None
    next_run_at: Optional[float] = None
    created_at: float
    updated_at: float

    class Config:
        from_attributes = True


class DailyCheckInSettingUpdate(BaseModel):
    enabled: bool
    game_id: Optional[str] = None


class DailyCheckInLogCreate(BaseModel):
    process_id: str
    process_name: Optional[str] = None
    user_preset_id: Optional[str] = None
    provider: str
    game_id: str
    game_name: Optional[str] = None
    period_start: float
    period_end: float
    attempted_at: float
    trigger: str
    status: str
    message: Optional[str] = None
    post_called: bool = False
    raw_debug_json: Optional[str] = None
    created_at: Optional[float] = None


class DailyCheckInLogSchema(BaseModel):
    id: int
    process_id: str
    process_name: Optional[str] = None
    user_preset_id: Optional[str] = None
    provider: str
    game_id: str
    game_name: Optional[str] = None
    period_start: float
    period_end: float
    attempted_at: float
    trigger: str
    status: str
    message: Optional[str] = None
    post_called: bool = False
    raw_debug_json: Optional[str] = None
    created_at: float

    class Config:
        from_attributes = True


class DailyCheckInRegisteredGameSchema(BaseModel):
    process_id: str
    process_name: str
    user_preset_id: Optional[str] = None
    provider: str
    provider_label: str
    game_id: str
    game_name: str
    reset_time_kst: str
    period_start: float
    period_end: float
    next_reset_at: float
    enabled: bool = False
    last_attempt_at: Optional[float] = None
    last_result: Optional[str] = None
    last_message: Optional[str] = None
    last_success_at: Optional[float] = None


class DailyCheckInRunRequest(BaseModel):
    process_id: str
    game_id: Optional[str] = None
    trigger: str = "manual_run"


class DailyCheckInRunDueRequest(BaseModel):
    trigger: str = "periodic"


class DailyCheckInStatusProbeRequest(BaseModel):
    process_id: str
    game_id: Optional[str] = None


class DailyCheckInStatusProbeSchema(BaseModel):
    process_id: str
    process_name: Optional[str] = None
    user_preset_id: Optional[str] = None
    provider: str
    game_id: str
    game_name: Optional[str] = None
    period_start: float
    period_end: float
    checked_at: float
    status: str
    message: Optional[str] = None
    post_called: bool = False
    raw_debug_json: Optional[str] = None


class ProviderCredentialHealthUpdate(BaseModel):
    provider: Optional[str] = None
    status: str = "unknown"
    reason: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = None
    process_id: Optional[str] = None
    game_id: Optional[str] = None
    detected_at: Optional[float] = None


class ProviderCredentialHealthSchema(BaseModel):
    provider: str
    status: str
    reason: Optional[str] = None
    message: Optional[str] = None
    source: Optional[str] = None
    process_id: Optional[str] = None
    game_id: Optional[str] = None
    detected_at: float
    created_at: float
    updated_at: float

    class Config:
        from_attributes = True
