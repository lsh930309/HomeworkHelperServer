"""
세션 관련 Pydantic 스키마
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class SessionCreateRequest(BaseModel):
    """세션 시작 요청 스키마"""
    process_id: int = Field(..., description="프로세스 ID")
    game_name: str = Field(..., min_length=1, max_length=100, description="게임 이름")


class SessionEndRequest(BaseModel):
    """세션 종료 요청 스키마"""
    end_ts: datetime = Field(..., description="종료 시각")


class SessionResponse(BaseModel):
    """세션 응답 스키마"""
    id: int
    user_id: int
    process_id: Optional[int]
    game_name: Optional[str]
    start_ts: datetime
    end_ts: Optional[datetime]
    duration: Optional[int]  # 초 단위
    created_at: datetime

    class Config:
        from_attributes = True


class SessionListResponse(BaseModel):
    """세션 목록 응답 스키마"""
    sessions: list[SessionResponse]
    total: int
