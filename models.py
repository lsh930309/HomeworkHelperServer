# models.py

from sqlalchemy import Column, Integer, String, Boolean, Float, JSON
from database import Base # 2단계에서 만든 database.py 파일에서 Base를 가져옵니다.

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
