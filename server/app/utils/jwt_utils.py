"""
JWT 토큰 생성 및 검증 유틸리티
"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from app.core.config import settings


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    JWT 액세스 토큰 생성

    Args:
        data: 토큰에 포함할 데이터 (예: {"sub": "user_id"})
        expires_delta: 토큰 만료 시간 (기본값: 설정에서 가져옴)

    Returns:
        str: JWT 토큰
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    """
    JWT 토큰 검증 및 디코딩

    Args:
        token: JWT 토큰 문자열

    Returns:
        dict | None: 토큰이 유효하면 페이로드, 아니면 None
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def get_user_id_from_token(token: str) -> Optional[int]:
    """
    JWT 토큰에서 사용자 ID 추출

    Args:
        token: JWT 토큰 문자열

    Returns:
        int | None: 사용자 ID, 토큰이 유효하지 않으면 None
    """
    payload = verify_token(token)
    if payload is None:
        return None

    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        return None

    try:
        return int(user_id)
    except ValueError:
        return None
