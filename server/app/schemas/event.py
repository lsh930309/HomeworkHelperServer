"""
이벤트 관련 Pydantic 스키마
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class EventCreateRequest(BaseModel):
    """이벤트 생성 요청 스키마"""
    session_id: int = Field(..., description="세션 ID")
    event_type: Optional[str] = Field(None, max_length=50, description="이벤트 타입 (예: resource_change, action_start)")
    resource_type: Optional[str] = Field(None, max_length=50, description="자원 타입 (예: stamina, currency)")
    value: Optional[int] = Field(None, description="이벤트 값")
    timestamp: datetime = Field(..., description="이벤트 발생 시각")


class EventResponse(BaseModel):
    """이벤트 응답 스키마"""
    id: int
    session_id: int
    event_type: Optional[str]
    resource_type: Optional[str]
    value: Optional[int]
    timestamp: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class EventListResponse(BaseModel):
    """이벤트 목록 응답 스키마"""
    events: list[EventResponse]
    total: int
