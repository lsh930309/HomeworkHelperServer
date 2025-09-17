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