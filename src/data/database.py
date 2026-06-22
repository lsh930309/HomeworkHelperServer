# database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
import os
import sys
from src.utils.app_paths import get_app_data_dir

"""데이터베이스 파일 저장 경로 설정
- 모든 환경: %APPDATA%/HomeworkHelper/homework_helper_data (권한 문제 방지)
- 개발 환경에서도 동일한 경로 사용 (일관성 유지)
"""

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
        "timeout": 5,
    },
    # Desktop host processes can run for days and may be restarted out-of-band
    # during packaging/update flows.  A pooled SQLite connection that is leaked
    # or wedged in one long-lived process can make every DB-backed HTTP route
    # wait forever even when the DB file itself is healthy.  NullPool keeps each
    # request/session on a short-lived SQLite connection and bounds lock waits
    # through the sqlite timeout/busy_timeout settings below.
    poolclass=NullPool,
)
# 'engine'은 SQLAlchemy가 데이터베이스와 소통하는 핵심 통로입니다.
# connect_args는 SQLite를 사용할 때만 필요한 옵션입니다.

# WAL 모드 활성화 (동시 읽기/쓰기 지원, 데이터 안전성 향상)
from sqlalchemy import event

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """SQLite 연결 시 WAL 모드 및 성능/안정성 PRAGMA를 설정합니다."""
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
        # Process 테이블 - 범용 외부 리소스 필드
        ("managed_processes", "resource_tracking_enabled", "INTEGER", "0"),
        ("managed_processes", "resource_provider", "TEXT", None),
        ("managed_processes", "resource_key", "TEXT", None),
        ("managed_processes", "resource_label", "TEXT", None),
        ("managed_processes", "resource_percent", "REAL", None),
        ("managed_processes", "resource_updated_at", "REAL", None),
        ("managed_processes", "resource_status", "TEXT", None),
        # Process 테이블 - 사용자 프리셋 ID
        ("managed_processes", "user_preset_id", "TEXT", None),  # 사용자 설정 프리셋 ID
        # Process 테이블 - 직접 실행 인자
        ("managed_processes", "launch_args_enabled", "INTEGER", "0"),
        ("managed_processes", "launch_args", "TEXT", "''"),
        # GlobalSettings 테이블 - 스태미나 알림 설정
        ("global_settings", "stamina_notify_enabled", "INTEGER", "1"),  # Boolean -> INTEGER
        ("global_settings", "stamina_notify_threshold", "INTEGER", "20"),
        # ProcessSession 테이블 - 사용자 프리셋 ID 및 스태미나 정보
        ("process_sessions", "user_preset_id", "TEXT", None),  # 사용자 설정 프리셋 ID
        ("process_sessions", "stamina_at_end", "INTEGER", None),
        ("process_sessions", "resource_percent_at_end", "REAL", None),
        ("process_sessions", "process_name", "TEXT", None),
        ("process_sessions", "session_duration", "REAL", None),
        # Beholder session metadata (nullable for legacy DB compatibility)
        ("process_sessions", "session_status", "TEXT", None),
        ("process_sessions", "session_owner", "TEXT", None),
        ("process_sessions", "heartbeat_timestamp", "REAL", None),
        ("process_sessions", "lease_token", "TEXT", None),
        ("process_sessions", "close_reason", "TEXT", None),
        ("process_sessions", "guard_flags", "TEXT", None),
        # Process 테이블 - 앱 볼륨 제어
        ("managed_processes", "default_volume", "INTEGER", None),
        ("managed_processes", "default_muted", "INTEGER", "0"),
        # GlobalSettings 테이블 - 테마 / 게임 모드
        ("global_settings", "theme", "TEXT", "'system'"),
        ("global_settings", "hide_on_game", "INTEGER", "1"),
        ("global_settings", "sidebar_enabled", "INTEGER", "1"),
        ("global_settings", "sidebar_mode", "TEXT", "'game'"),
        ("global_settings", "sidebar_trigger_y_start", "REAL", "0.1"),
        ("global_settings", "sidebar_trigger_y_end", "REAL", "0.9"),
        ("global_settings", "sidebar_handle_auto_hide", "INTEGER", "1"),
        ("global_settings", "sidebar_auto_hide_ms", "INTEGER", "3000"),
        ("global_settings", "sidebar_edge_width_px", "INTEGER", "2"),
        ("global_settings", "sidebar_height_ratio", "REAL", "1.0"),
        ("global_settings", "sidebar_opacity", "REAL", "0.85"),
        ("global_settings", "sidebar_clock_enabled", "INTEGER", "1"),
        ("global_settings", "sidebar_clock_format", "TEXT", "'%H:%M:%S'"),
        ("global_settings", "sidebar_playtime_enabled", "INTEGER", "1"),
        ("global_settings", "sidebar_playtime_prefix", "TEXT", "'오늘 플레이 시간'"),
        ("global_settings", "sidebar_volume_section_enabled", "INTEGER", "1"),
        # GlobalSettings 테이블 - 스크린샷 설정
        ("global_settings", "screenshot_enabled", "INTEGER", "1"),
        ("global_settings", "screenshot_save_dir", "TEXT", "''"),
        ("global_settings", "screenshot_gamepad_trigger", "INTEGER", "1"),
        ("global_settings", "screenshot_disable_gamebar", "INTEGER", "0"),
        ("global_settings", "screenshot_capture_mode", "TEXT", "'fullscreen'"),
        ("global_settings", "screenshot_gamepad_button_index", "INTEGER", "-1"),
        ("global_settings", "screenshot_trigger_vk", "INTEGER", "178"),
        # Recording (OBS)
        ("global_settings", "recording_enabled", "INTEGER", "0"),
        ("global_settings", "obs_host", "TEXT", "'localhost'"),
        ("global_settings", "obs_port", "INTEGER", "4455"),
        ("global_settings", "obs_password", "TEXT", "''"),
        ("global_settings", "obs_exe_path", "TEXT", "''"),
        ("global_settings", "obs_auto_launch", "INTEGER", "0"),
        ("global_settings", "obs_launch_hidden", "INTEGER", "1"),
        ("global_settings", "obs_watch_output_dir", "INTEGER", "1"),
        ("global_settings", "obs_recording_output_dir", "TEXT", "''"),
        ("global_settings", "recording_hold_threshold_ms", "INTEGER", "800"),
        # Remote server mode
        ("global_settings", "remote_server_mode_enabled", "INTEGER", "0"),
        # Beholder incident UX / resolution metadata
        ("beholder_incidents", "user_title", "TEXT", None),
        ("beholder_incidents", "user_summary", "TEXT", None),
        ("beholder_incidents", "user_impact", "TEXT", None),
        ("beholder_incidents", "recommended_action", "TEXT", None),
        ("beholder_incidents", "available_actions", "TEXT", None),
        ("beholder_incidents", "resolution_metadata", "TEXT", None),
    ]
    
    try:
        inspector = inspect(engine)
        added_columns: set[tuple[str, str]] = set()
        
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS app_runtime_heartbeats ("
                "id INTEGER PRIMARY KEY, "
                "app_instance_id TEXT, "
                "runtime_kind TEXT, "
                "boot_id TEXT, "
                "started_at REAL, "
                "last_heartbeat_at REAL, "
                "last_shutdown_at REAL"
                ")"
            ))
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS daily_checkin_settings ("
                "process_id TEXT PRIMARY KEY, "
                "process_name TEXT, "
                "user_preset_id TEXT, "
                "provider TEXT NOT NULL, "
                "game_id TEXT NOT NULL, "
                "game_name TEXT, "
                "enabled INTEGER NOT NULL DEFAULT 0, "
                "last_attempt_at REAL, "
                "last_result TEXT, "
                "last_message TEXT, "
                "last_period_start REAL, "
                "last_success_at REAL, "
                "next_run_at REAL, "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_daily_checkin_settings_enabled "
                "ON daily_checkin_settings (enabled)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_daily_checkin_settings_provider_game "
                "ON daily_checkin_settings (provider, game_id)"
            ))
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS daily_checkin_logs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "process_id TEXT NOT NULL, "
                "process_name TEXT, "
                "user_preset_id TEXT, "
                "provider TEXT NOT NULL, "
                "game_id TEXT NOT NULL, "
                "game_name TEXT, "
                "period_start REAL NOT NULL, "
                "period_end REAL NOT NULL, "
                "attempted_at REAL NOT NULL, "
                "trigger TEXT NOT NULL, "
                "status TEXT NOT NULL, "
                "message TEXT, "
                "post_called INTEGER NOT NULL DEFAULT 0, "
                "raw_debug_json TEXT, "
                "created_at REAL NOT NULL"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_daily_checkin_logs_process_game_period "
                "ON daily_checkin_logs (process_id, game_id, period_start)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_daily_checkin_logs_attempted_at "
                "ON daily_checkin_logs (attempted_at)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_daily_checkin_logs_provider_game "
                "ON daily_checkin_logs (provider, game_id)"
            ))
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS provider_credential_health ("
                "provider TEXT PRIMARY KEY, "
                "status TEXT NOT NULL DEFAULT 'unknown', "
                "reason TEXT, "
                "message TEXT, "
                "source TEXT, "
                "process_id TEXT, "
                "game_id TEXT, "
                "detected_at REAL NOT NULL, "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_provider_credential_health_status "
                "ON provider_credential_health (status)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_provider_credential_health_detected_at "
                "ON provider_credential_health (detected_at)"
            ))
            conn.commit()
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS game_platform_links ("
                "id TEXT PRIMARY KEY, "
                "pc_process_id TEXT NOT NULL, "
                "pc_display_name TEXT, "
                "android_package_name TEXT NOT NULL, "
                "android_launch_intent_uri TEXT, "
                "android_store_url TEXT, "
                "platform_account_hint TEXT, "
                "hoyolab_game_id TEXT, "
                "sync_strategy TEXT NOT NULL DEFAULT 'manual', "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_game_platform_links_pc_process_id "
                "ON game_platform_links (pc_process_id)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_game_platform_links_android_package_name "
                "ON game_platform_links (android_package_name)"
            ))
            conn.commit()
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS mobile_game_sessions ("
                "id TEXT PRIMARY KEY, "
                "game_link_id TEXT NOT NULL, "
                "pc_process_id TEXT NOT NULL, "
                "pc_display_name TEXT, "
                "android_package_name TEXT NOT NULL, "
                "source TEXT NOT NULL DEFAULT 'manual', "
                "status TEXT NOT NULL DEFAULT 'active', "
                "started_at REAL NOT NULL, "
                "ended_at REAL, "
                "duration_seconds REAL, "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_mobile_game_sessions_status_started_at "
                "ON mobile_game_sessions (status, started_at)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_mobile_game_sessions_game_link_id "
                "ON mobile_game_sessions (game_link_id)"
            ))
            conn.commit()
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
                added_columns.add((table_name, column_name))
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
            if {"resource_provider", "resource_key", "resource_label"}.issubset(existing_columns):
                result = conn.execute(text(
                    "UPDATE managed_processes "
                    "SET resource_label = '전초기지 방어 보상' "
                    "WHERE resource_provider = 'nikke_blablalink' "
                    "AND resource_key = 'nikke_outpost_storage' "
                    "AND (resource_label IS NULL OR resource_label = '' OR resource_label = '보관함 용량')"
                ))
                conn.commit()
                if result.rowcount > 0:
                    print(f"[Migration] managed_processes: NIKKE resource_label {result.rowcount}개 보정 완료")

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

        # sidebar_auto_hide_sec → sidebar_auto_hide_ms 데이터 마이그레이션
        with engine.connect() as conn:
            existing_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(global_settings)"))]
            if "sidebar_auto_hide_sec" in existing_columns and "sidebar_auto_hide_ms" in existing_columns:
                conn.execute(text(
                    "UPDATE global_settings SET sidebar_auto_hide_ms = COALESCE(sidebar_auto_hide_sec, 3) * 1000 "
                    "WHERE sidebar_auto_hide_ms = 3000"
                ))
                conn.commit()

            if "sidebar_mode" in existing_columns and "sidebar_enabled" in existing_columns:
                mode_where = (
                    "1 = 1"
                    if ("global_settings", "sidebar_mode") in added_columns
                    else "sidebar_mode IS NULL OR sidebar_mode = '' OR sidebar_mode NOT IN ('always', 'game', 'disabled')"
                )
                conn.execute(text(
                    "UPDATE global_settings "
                    "SET sidebar_mode = CASE WHEN COALESCE(sidebar_enabled, 1) = 0 THEN 'disabled' ELSE 'game' END "
                    f"WHERE {mode_where}"
                ))
                conn.commit()

        with engine.connect() as conn:
            if "beholder_incidents" in inspector.get_table_names():
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_beholder_incidents_status_created_at "
                    "ON beholder_incidents (status, created_at)"
                ))
                conn.commit()

        print("[Migration] 자동 마이그레이션 완료")
    except Exception as e:
        print(f"[Migration] 마이그레이션 중 오류 (무시됨): {e}")


# 5. DB 롤링 백업 함수
def backup_database(max_backups: int = 3) -> bool:
    """앱 시작 시 이전 세션의 DB를 롤링 백업합니다.

    SQLite Online Backup API를 사용하므로 DB가 열려 있어도 안전하게 백업됩니다.

    백업 위치: %APPDATA%/HomeworkHelper/backups/
    파일명: app_data.backup.1.db (최신) ~ app_data.backup.{max_backups}.db (가장 오래된)
    """
    import sqlite3 as _sqlite3

    if max_backups < 1:
        print(f"[Backup] max_backups 값이 유효하지 않습니다: {max_backups}")
        return False

    if not os.path.exists(db_path):
        print("[Backup] DB 파일이 없어 백업을 건너뜁니다. (최초 실행)")
        return False

    backup_dir = os.path.join(base_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)

    try:
        import contextlib
        # 롤링: backup.N 삭제 → backup.(N-1)→N 순으로 밀기
        for i in range(max_backups, 0, -1):
            current = os.path.join(backup_dir, f"app_data.backup.{i}.db")
            if i == max_backups:
                if os.path.exists(current):
                    os.remove(current)
            else:
                next_slot = os.path.join(backup_dir, f"app_data.backup.{i + 1}.db")
                if os.path.exists(current):
                    os.rename(current, next_slot)

        # 현재 DB → backup.1.db (SQLite Online Backup API, 원자적 교체)
        backup_path = os.path.join(backup_dir, "app_data.backup.1.db")
        temp_path = backup_path + ".tmp"
        replaced = False
        try:
            with contextlib.closing(_sqlite3.connect(db_path)) as src_conn:
                with contextlib.closing(_sqlite3.connect(temp_path)) as dst_conn:
                    src_conn.backup(dst_conn)
            os.replace(temp_path, backup_path)
            replaced = True
        finally:
            if not replaced and os.path.exists(temp_path):
                os.remove(temp_path)
    except Exception as e:
        print(f"[Backup] DB 백업 실패 (무시됨): {e}")
        return False
    else:
        print(f"[Backup] DB 백업 완료: {backup_path}")
        return True


# 6. 안전한 데이터베이스 종료 함수 (선택사항 - 추가 안전장치)
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
