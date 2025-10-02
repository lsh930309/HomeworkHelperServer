# database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os, sys

"""데이터베이스 파일 저장 경로 설정
- 패키징(.exe) 환경: 실행 파일(.exe)과 같은 경로의 homework_helper_data
- 개발 환경: 현재 파일 기준 프로젝트 경로의 homework_helper_data
"""
if getattr(sys, 'frozen', False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

data_dir = os.path.join(base_dir, "homework_helper_data")
os.makedirs(data_dir, exist_ok=True)

db_path = os.path.join(data_dir, "app_data.db")
# Windows 백슬래시를 URL 포맷에 맞게 슬래시로 변환
db_path_url = db_path.replace("\\", "/")

SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path_url}"

# 2. 데이터베이스 엔진 생성
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={
        "check_same_thread": False,
    }
)
# 'engine'은 SQLAlchemy가 데이터베이스와 소통하는 핵심 통로입니다.
# connect_args는 SQLite를 사용할 때만 필요한 옵션입니다.

# WAL 모드 활성화 (동시 읽기/쓰기 지원, 데이터 안전성 향상)
from sqlalchemy import event

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

# 3. 데이터베이스 세션 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# '세션'은 DB와 대화하기 위한 창구입니다. 
# 이 SessionLocal을 통해 DB에 데이터를 추가, 수정, 삭제하는 작업을 수행합니다.

# 4. 데이터베이스 모델의 부모 클래스 생성
Base = declarative_base()
# 앞으로 만들 DB 테이블 모델들은 모두 이 Base 클래스를 상속받아 만들어집니다.