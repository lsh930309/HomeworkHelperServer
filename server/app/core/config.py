"""
환경 변수 및 설정 관리
"""
from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """애플리케이션 설정"""

    # 데이터베이스 설정
    DATABASE_URL: str

    # JWT 인증 설정
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30일 (30 * 24 * 60)

    # API 서버 설정
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_PREFIX: str = "/api/v1"

    # CORS 설정 (Android 앱 연동)
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://192.168.56.1:8000",  # Host PC (VM 환경)
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]

    # 프로젝트 정보
    PROJECT_NAME: str = "HomeworkHelper API"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "Phase 1: VM 로컬 서버"

    class Config:
        env_file = ".env"
        case_sensitive = True


# 전역 설정 인스턴스
settings = Settings()
