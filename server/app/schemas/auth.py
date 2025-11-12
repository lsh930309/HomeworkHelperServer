"""
인증 관련 Pydantic 스키마
"""
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class UserRegisterRequest(BaseModel):
    """회원가입 요청 스키마"""
    username: str = Field(..., min_length=3, max_length=50, description="사용자 이름")
    email: EmailStr = Field(..., description="이메일 주소")
    password: str = Field(..., min_length=8, max_length=100, description="비밀번호 (8자 이상)")


class UserLoginRequest(BaseModel):
    """로그인 요청 스키마"""
    username: str = Field(..., description="사용자 이름")
    password: str = Field(..., description="비밀번호")


class TokenResponse(BaseModel):
    """JWT 토큰 응답 스키마"""
    access_token: str = Field(..., description="JWT 액세스 토큰")
    token_type: str = Field(default="bearer", description="토큰 타입")
    user_id: int = Field(..., description="사용자 ID")
    username: str = Field(..., description="사용자 이름")


class UserResponse(BaseModel):
    """사용자 정보 응답 스키마"""
    id: int
    username: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True  # SQLAlchemy 모델을 Pydantic으로 변환 허용
