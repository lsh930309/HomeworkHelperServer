"""
데이터베이스 연결 및 세션 관리
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# SQLAlchemy 엔진 생성
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,  # 연결 유효성 자동 확인
    pool_size=5,  # 커넥션 풀 크기
    max_overflow=10,  # 최대 추가 연결 수
    echo=False,  # SQL 로그 출력 (디버그 시 True)
)

# 세션 팩토리
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base 클래스 (모든 모델이 상속)
Base = declarative_base()


def get_db():
    """
    데이터베이스 세션 의존성
    FastAPI Dependency Injection에서 사용

    Yields:
        Session: 데이터베이스 세션
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    데이터베이스 초기화
    모든 테이블 생성 (프로덕션에서는 Alembic 사용)
    """
    Base.metadata.create_all(bind=engine)
