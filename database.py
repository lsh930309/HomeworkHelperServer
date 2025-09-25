# database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os, sys

# 1. 데이터베이스 파일 절대 경로 설정 (패키지/개발 환경 모두 일관)
# 패키지(배포) 환경에서는 사용자 프로필 하위에 저장하여 권한/일관성 문제 예방
if getattr(sys, 'frozen', False):
    appdata_dir = os.environ.get('APPDATA') or os.path.expanduser('~')
    data_dir = os.path.join(appdata_dir, "HomeworkHelper")
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
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
# 'engine'은 SQLAlchemy가 데이터베이스와 소통하는 핵심 통로입니다.
# connect_args는 SQLite를 사용할 때만 필요한 옵션입니다.

# 3. 데이터베이스 세션 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# '세션'은 DB와 대화하기 위한 창구입니다. 
# 이 SessionLocal을 통해 DB에 데이터를 추가, 수정, 삭제하는 작업을 수행합니다.

# 4. 데이터베이스 모델의 부모 클래스 생성
Base = declarative_base()
# 앞으로 만들 DB 테이블 모델들은 모두 이 Base 클래스를 상속받아 만들어집니다.