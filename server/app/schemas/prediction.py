"""
예측 관련 Pydantic 스키마
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class PredictionCreateRequest(BaseModel):
    """예측 생성 요청 스키마"""
    session_id: int = Field(..., description="세션 ID")
    predicted_action: Optional[str] = Field(None, max_length=100, description="예측된 행동 (예: raid, daily_quest)")
    predicted_value: Optional[int] = Field(None, description="예상 자원량")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="신뢰도 (0.0 ~ 1.0)")


class PredictionResponse(BaseModel):
    """예측 응답 스키마"""
    id: int
    session_id: int
    predicted_action: Optional[str]
    predicted_value: Optional[int]
    confidence: Optional[float]
    created_at: datetime

    class Config:
        from_attributes = True


class PredictionListResponse(BaseModel):
    """예측 목록 응답 스키마"""
    predictions: list[PredictionResponse]
    total: int
