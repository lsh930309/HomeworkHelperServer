# database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os, sys

"""데이터베이스 파일 저장 경로 설정
- 모든 환경: %APPDATA%/HomeworkHelper/homework_helper_data (권한 문제 방지)
- 개발 환경에서도 동일한 경로 사용 (일관성 유지)
"""
def get_app_data_dir():
    """애플리케이션 데이터 디렉토리 경로 반환 (%APPDATA%/HomeworkHelper)"""
    if os.name == 'nt':  # Windows
        app_data = os.getenv('APPDATA')
        if not app_data:
            # fallback: 사용자 홈 디렉토리
            app_data = os.path.expanduser('~')
    else:  # Linux/Mac (향후 대비)
        app_data = os.path.expanduser('~/.config')

    app_dir = os.path.join(app_data, 'HomeworkHelper')
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

base_dir = get_app_data_dir()
data_dir = os.path.join(base_dir, "homework_helper_data")
os.makedirs(data_dir, exist_ok=True)

print(f"데이터 디렉토리: {data_dir}")

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
    cursor.execute("PRAGMA synchronous=FULL")  # PC 강제 종료 시 데이터 손실 방지
    cursor.execute("PRAGMA wal_autocheckpoint=20")  # 20 페이지마다 자동 checkpoint (더 자주)
    cursor.execute("PRAGMA busy_timeout=5000")  # 락 대기 시간 5초 (기본 0)
    cursor.execute("PRAGMA cache_size=-64000")  # 64MB 캐시 (성능 향상)
    cursor.close()

# 3. 데이터베이스 세션 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# '세션'은 DB와 대화하기 위한 창구입니다. 
# 이 SessionLocal을 통해 DB에 데이터를 추가, 수정, 삭제하는 작업을 수행합니다.

# 4. 데이터베이스 모델의 부모 클래스 생성
Base = declarative_base()
# 앞으로 만들 DB 테이블 모델들은 모두 이 Base 클래스를 상속받아 만들어집니다.

# 5. 안전한 데이터베이스 종료 함수 (선택사항 - 추가 안전장치)
def safe_shutdown_database():
    """
    데이터베이스를 안전하게 종료합니다.
    - WAL 체크포인트 실행 (.wal 내용을 .db로 완전 이동)
    - 모든 연결 정리

    주의: 이 함수는 서버 종료 시 자동으로 호출되므로 일반적으로 직접 호출할 필요 없음
    """
    from sqlalchemy import text

    try:
        # WAL 체크포인트 (TRUNCATE 모드: .wal 내용을 .db로 이동 후 .wal 삭제)
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
            checkpoint_result = result.fetchone()
            print(f"WAL 체크포인트 결과: {checkpoint_result}")

        # 모든 연결 정리
        engine.dispose()
        print("데이터베이스 안전 종료 완료")
    except Exception as e:
        print(f"데이터베이스 종료 중 오류: {e}")