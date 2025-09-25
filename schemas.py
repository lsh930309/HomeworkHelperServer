from pydantic import BaseModel
from typing import List, Optional

class ProcessSchema(BaseModel):
    id: str
    name: str
    monitoring_path: str
    launch_path: str
    server_reset_time_str: Optional[str] = None
    user_cycle_hours: Optional[int] = 24
    mandatory_times_str: Optional[List[str]] = None
    is_mandatory_time_enabled: bool = False
    last_played_timestamp: Optional[float] = None
    original_launch_path: Optional[str] = None

class ProcessCreateSchema(BaseModel):
    name: str
    monitoring_path: str
    launch_path: str
    server_reset_time_str: Optional[str] = None
    user_cycle_hours: Optional[int] = 24
    mandatory_times_str: Optional[List[str]] = None
    is_mandatory_time_enabled: bool = False

class WebShortcutBase(BaseModel):
    name: str = ""
    url: str = ""
    refresh_time_str: Optional[str] = None
    last_reset_timestamp: Optional[float] = None

class WebShortcutCreate(WebShortcutBase):
    pass

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
    lock_window_resize: bool = False
    always_on_top: bool = False
    run_as_admin: bool = False
    notify_on_launch_success: bool = True
    notify_on_launch_failure: bool = True
    notify_on_mandatory_time: bool = True
    notify_on_cycle_deadline: bool = True
    notify_on_sleep_correction: bool = True
    notify_on_daily_reset: bool = True