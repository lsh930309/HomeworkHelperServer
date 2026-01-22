# models.py

from sqlalchemy import Column, Integer, String, Boolean, Float, JSON
from src.data.database import Base

class Process(Base):
    __tablename__ = "managed_processes"

    # 각 컬럼(표의 열)을 정의합니다.
    # 기존 ManagedProcess 클래스의 속성들을 DB 테이블의 컬럼으로 만듭니다.
    
    id = Column(String, primary_key=True, index=True) # 고유 ID, 기본 키로 설정
    name = Column(String, index=True)
    monitoring_path = Column(String)
    launch_path = Column(String)
    
    server_reset_time_str = Column(String, nullable=True) # 값이 없어도 됨 (NULL 허용)
    user_cycle_hours = Column(Integer, default=24)
    
    # 리스트(List)는 기본 데이터 타입이 아니므로, JSON 형태로 저장합니다.
    mandatory_times_str = Column(JSON, default=[]) 
    
    is_mandatory_time_enabled = Column(Boolean, default=False)
    last_played_timestamp = Column(Float, nullable=True)
    original_launch_path = Column(String, nullable=True)
    preferred_launch_type = Column(String, default="shortcut")  # 실행 방식 선호도
    game_schema_id = Column(String, nullable=True)  # 게임 스키마 ID
    mvp_enabled = Column(Boolean, default=False)    # MVP 기능 플래그

    # HoYoLab 스태미나 연동 필드
    stamina_tracking_enabled = Column(Boolean, default=False)  # 스태미나 자동 추적 활성화
    hoyolab_game_id = Column(String, nullable=True)      # 추적할 호요버스 게임 ID
    stamina_current = Column(Integer, nullable=True)      # 현재 스태미나
    stamina_max = Column(Integer, nullable=True)          # 최대 스태미나 (API에서 가져옴)
    stamina_updated_at = Column(Float, nullable=True)     # 마지막 스태미나 조회 시각 (timestamp)


class WebShortcut(Base):
    __tablename__ = "web_shortcuts"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, index=True)
    url = Column(String)
    refresh_time_str = Column(String, nullable=True)
    last_reset_timestamp = Column(Float, nullable=True)


class GlobalSettings(Base):
    __tablename__ = "global_settings"

    # 이 테이블은 항상 id=1인 행 하나만 가질 것입니다.
    id = Column(Integer, primary_key=True, default=1)

    sleep_start_time_str = Column(String, default="00:00")
    sleep_end_time_str = Column(String, default="08:00")
    sleep_correction_advance_notify_hours = Column(Float, default=1.0)
    cycle_deadline_advance_notify_hours = Column(Float, default=2.0)
    run_on_startup = Column(Boolean, default=False)
    always_on_top = Column(Boolean, default=False)
    run_as_admin = Column(Boolean, default=False)
    notify_on_launch_success = Column(Boolean, default=True)
    notify_on_launch_failure = Column(Boolean, default=True)
    notify_on_mandatory_time = Column(Boolean, default=True)
    notify_on_cycle_deadline = Column(Boolean, default=True)
    notify_on_sleep_correction = Column(Boolean, default=True)
    notify_on_daily_reset = Column(Boolean, default=True)
    
    # 스태미나 알림 설정 (호요버스 게임)
    stamina_notify_enabled = Column(Boolean, default=True)
    stamina_notify_threshold = Column(Integer, default=20)  # 최대 - N 이상일 때 알림


class ProcessSession(Base):
    """게임/프로세스 실행 세션 타임스탬프 기록"""
    __tablename__ = "process_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    process_id = Column(String, index=True)  # Process 테이블의 id 참조
    process_name = Column(String, index=True)  # 프로세스 이름 (중복 저장, 조회 성능 향상)
    start_timestamp = Column(Float, nullable=False, index=True)  # 실행 시작 시간
    end_timestamp = Column(Float, nullable=True)  # 종료 시간 (실행 중이면 NULL)
    session_duration = Column(Float, nullable=True)  # 세션 길이 (초 단위, 종료 시 계산)
    game_schema_id = Column(String, nullable=True)  # 게임 스키마 ID
    stamina_at_end = Column(Integer, nullable=True)  # 종료 시점 스태미나