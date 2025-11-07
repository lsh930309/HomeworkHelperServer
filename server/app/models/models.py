"""
SQLAlchemy 데이터베이스 모델 (SQLAlchemy 2.0 스타일 적용)
"""
from sqlalchemy import (
    Integer, String, Float, DateTime, ForeignKey, func
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from app.core.database import Base


class User(Base):
    """사용자 모델"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    sessions: Mapped[list["Session"]] = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    """게임 세션 모델"""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    process_id: Mapped[int | None] = mapped_column(Integer)
    game_name: Mapped[str | None] = mapped_column(String(100))
    start_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_ts: Mapped[datetime | None] = mapped_column(DateTime)
    duration: Mapped[int | None] = mapped_column()  # 초 단위
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="session", cascade="all, delete-orphan")
    predictions: Mapped[list["Prediction"]] = relationship("Prediction", back_populates="session", cascade="all, delete-orphan")


class Event(Base):
    """이벤트 모델 (자원 변화 등)"""
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str | None] = mapped_column(String(50))  # "resource_change", "action_start", etc.
    resource_type: Mapped[str | None] = mapped_column(String(50))  # "stamina", "currency", etc.
    value: Mapped[int | None] = mapped_column()
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    session: Mapped["Session"] = relationship("Session", back_populates="events")


class Prediction(Base):
    """예측 모델 (AI 추천)"""
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    predicted_action: Mapped[str | None] = mapped_column(String(100))  # "raid", "daily_quest", etc.
    predicted_value: Mapped[int | None] = mapped_column()  # 예상 자원량
    confidence: Mapped[float | None] = mapped_column()  # 0.0 ~ 1.0
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    session: Mapped["Session"] = relationship("Session", back_populates="predictions")
