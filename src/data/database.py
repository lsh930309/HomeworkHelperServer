# database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import sys

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


def auto_migrate_database():
    """
    자동 마이그레이션 실행 - 새 컬럼이 없으면 추가합니다.
    
    SQLAlchemy의 create_all()은 기존 테이블에 새 컬럼을 추가하지 않으므로,
    앱 시작 시 이 함수를 호출하여 스키마를 동기화합니다.
    """
    from sqlalchemy import text, inspect
    
    migrations = [
        # (테이블명, 컬럼명, SQL 타입, 기본값)
        # Process 테이블 - 스태미나 필드
        ("managed_processes", "stamina_tracking_enabled", "INTEGER", "0"),  # Boolean -> INTEGER
        ("managed_processes", "hoyolab_game_id", "TEXT", None),  # 추적할 호요버스 게임 ID
        ("managed_processes", "stamina_current", "INTEGER", None),
        ("managed_processes", "stamina_max", "INTEGER", None),
        ("managed_processes", "stamina_updated_at", "REAL", None),
        # Process 테이블 - 사용자 프리셋 ID
        ("managed_processes", "user_preset_id", "TEXT", None),  # 사용자 설정 프리셋 ID
        # GlobalSettings 테이블 - 스태미나 알림 설정
        ("global_settings", "stamina_notify_enabled", "INTEGER", "1"),  # Boolean -> INTEGER
        ("global_settings", "stamina_notify_threshold", "INTEGER", "20"),
        # ProcessSession 테이블 - 사용자 프리셋 ID 및 스태미나 정보
        ("process_sessions", "user_preset_id", "TEXT", None),  # 사용자 설정 프리셋 ID
        ("process_sessions", "stamina_at_end", "INTEGER", None),
    ]
    
    try:
        inspector = inspect(engine)
        
        with engine.connect() as conn:
            for table_name, column_name, column_type, default_value in migrations:
                # 테이블 존재 여부 확인
                if table_name not in inspector.get_table_names():
                    continue
                
                # 컬럼 존재 여부 확인
                existing_columns = [col['name'] for col in inspector.get_columns(table_name)]
                if column_name in existing_columns:
                    continue
                
                # 컬럼 추가
                if default_value is not None:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type} DEFAULT {default_value}"
                else:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                
                conn.execute(text(sql))
                conn.commit()
                print(f"[Migration] {table_name}.{column_name} 컬럼 추가됨")

        # 데이터 마이그레이션: game_schema_id → user_preset_id 복사
        with engine.connect() as conn:
            # managed_processes 테이블
            existing_columns = [col['name'] for col in inspector.get_columns("managed_processes")]
            if "game_schema_id" in existing_columns and "user_preset_id" in existing_columns:
                # game_schema_id 값을 user_preset_id로 복사 (NULL이 아닌 것만)
                result = conn.execute(text(
                    "UPDATE managed_processes SET user_preset_id = game_schema_id "
                    "WHERE game_schema_id IS NOT NULL AND user_preset_id IS NULL"
                ))
                conn.commit()
                if result.rowcount > 0:
                    print(f"[Migration] managed_processes: {result.rowcount}개 행의 game_schema_id → user_preset_id 복사 완료")

            # process_sessions 테이블
            existing_columns = [col['name'] for col in inspector.get_columns("process_sessions")]
            if "game_schema_id" in existing_columns and "user_preset_id" in existing_columns:
                # game_schema_id 값을 user_preset_id로 복사 (NULL이 아닌 것만)
                result = conn.execute(text(
                    "UPDATE process_sessions SET user_preset_id = game_schema_id "
                    "WHERE game_schema_id IS NOT NULL AND user_preset_id IS NULL"
                ))
                conn.commit()
                if result.rowcount > 0:
                    print(f"[Migration] process_sessions: {result.rowcount}개 행의 game_schema_id → user_preset_id 복사 완료")

        print("[Migration] 자동 마이그레이션 완료")
    except Exception as e:
        print(f"[Migration] 마이그레이션 중 오류 (무시됨): {e}")


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