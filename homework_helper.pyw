import sys
import datetime
import os
import functools
import ctypes
import subprocess
import atexit
import time
from typing import List, Optional, Dict, Any

api_server_process = None

# 새로 분리된 모듈 imports
from admin_utils import check_admin_requirement, is_admin
from migration import run_automatic_migration
from main_window import MainWindow
from instance_manager import run_with_single_instance_check, SingleInstanceApplication
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFontDatabase, QFont
from utils import get_bundle_resource_path
from api_client import ApiClient

# Windows 전용 모듈 임포트 (선택적)
if os.name == 'nt':
    try:
        import win32api
        import win32security
        WINDOWS_SECURITY_AVAILABLE = True
    except ImportError:
        WINDOWS_SECURITY_AVAILABLE = False
else:
    WINDOWS_SECURITY_AVAILABLE = False

def wait_for_server_ready(max_wait_seconds: int = 10) -> bool:
    """서버가 준비될 때까지 대기합니다."""
    print("API 서버 준비 대기 중...")
    import requests
    base_url = "http://127.0.0.1:8000"
    iterations = int(max_wait_seconds / 0.2)

    for i in range(iterations):
        try:
            # /settings 엔드포인트에 GET 요청을 보내 서버 상태 확인
            response = requests.get(f"{base_url}/settings", timeout=0.5)
            if response.status_code == 200:
                print(f"API 서버 준비 완료. ({i * 0.2:.1f}초 소요)")
                return True
        except requests.ConnectionError:
            time.sleep(0.2)
        except Exception as e:
            print(f"API 서버 확인 중 오류: {e}")
            time.sleep(0.2)

    print("API 서버가 시간 내에 응답하지 않았습니다.")
    return False

def get_app_data_dir():
    """애플리케이션 데이터 디렉토리 경로 반환 (%APPDATA%/HomeworkHelper)"""
    if os.name == 'nt':  # Windows
        app_data = os.getenv('APPDATA')
        if not app_data:
            app_data = os.path.expanduser('~')
    else:  # Linux/Mac
        app_data = os.path.expanduser('~/.config')

    app_dir = os.path.join(app_data, 'HomeworkHelper')
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

def is_server_running() -> bool:
    """
    Windows Named Mutex를 사용하여 서버가 실행 중인지 확인합니다.
    PID 파일보다 훨씬 안정적입니다 (OS 수준에서 자동 관리).
    """
    if os.name != 'nt':
        # Windows 아닌 경우 PID 파일 fallback
        return is_server_running_pid_fallback()

    try:
        import win32event
        import win32api
        import winerror

        mutex_name = "Global\\HomeworkHelperDBServerMutex"

        # 뮤텍스 열기 시도 (이미 존재하면 서버 실행 중)
        try:
            mutex_handle = win32event.OpenMutex(win32api.GENERIC_READ, False, mutex_name)
            win32api.CloseHandle(mutex_handle)
            return True  # 뮤텍스 존재 = 서버 실행 중
        except Exception as e:
            if getattr(e, 'winerror', None) == winerror.ERROR_FILE_NOT_FOUND:
                return False  # 뮤텍스 없음 = 서버 미실행
            else:
                # 다른 오류 발생 시 PID 파일로 fallback
                print(f"Mutex 확인 오류: {e}, PID 파일로 fallback")
                return is_server_running_pid_fallback()
    except ImportError:
        # pywin32 없으면 PID 파일 fallback
        print("pywin32 없음, PID 파일로 fallback")
        return is_server_running_pid_fallback()

def is_server_running_pid_fallback() -> bool:
    """PID 파일을 확인하여 서버가 실행 중인지 확인 (Fallback 방법)"""
    data_dir = os.path.join(get_app_data_dir(), "homework_helper_data")
    pid_file = os.path.join(data_dir, "db_server.pid")

    if not os.path.exists(pid_file):
        return False

    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())

        # PID가 실제로 실행 중인지 확인
        import psutil
        if psutil.pid_exists(pid):
            try:
                proc = psutil.Process(pid)
                # 프로세스가 존재하고 좀비가 아닌지 확인
                return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False
        return False
    except (ValueError, IOError):
        return False

def start_api_server() -> bool:
    """FastAPI 서버를 독립 프로세스로 실행합니다."""
    global api_server_process
    try:
        # 이미 서버가 실행 중인지 확인
        if is_server_running():
            print("API 서버가 이미 실행 중입니다. 기존 서버를 사용합니다.")
            # 서버가 준비될 때까지 대기
            if wait_for_server_ready():
                return True
            else:
                print("기존 서버가 응답하지 않습니다. 서버를 재시작합니다.")
                # PID 파일 삭제하고 재시작
                data_dir = os.path.join(get_app_data_dir(), "homework_helper_data")
                pid_file = os.path.join(data_dir, "db_server.pid")
                try:
                    os.remove(pid_file)
                except:
                    pass

        if getattr(sys, 'frozen', False):
            # 패키지 환경: 자기 자신(.exe)을 '--run-server' 인자와 함께 실행
            command = [sys.executable, "--run-server"]
        else:
            # 개발 환경: uvicorn을 직접 실행
            command = [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]

        print(f"API 서버 실행 명령어: {' '.join(command)}")

        # Windows에서 완전히 독립적인 프로세스로 실행
        if os.name == 'nt':
            # CREATE_NO_WINDOW: 콘솔 창 생성 안 함
            # CREATE_NEW_PROCESS_GROUP: 새로운 프로세스 그룹 (Ctrl+C 신호 독립)
            # CREATE_BREAKAWAY_FROM_JOB: Job Object에서 독립 (부모 종료 시 영향 없음)
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                creationflags |= subprocess.CREATE_BREAKAWAY_FROM_JOB
            except AttributeError:
                # Python 3.7 이하에서는 CREATE_BREAKAWAY_FROM_JOB이 없을 수 있음
                creationflags |= 0x01000000  # CREATE_BREAKAWAY_FROM_JOB 값
        else:
            creationflags = 0

        # CREATE_NO_WINDOW 사용 시 stdout/stderr이 None이 되어 uvicorn 로깅 설정에서 오류 발생
        # 이를 방지하기 위해 stdout과 stderr를 DEVNULL로 리디렉션합니다.
        api_server_process = subprocess.Popen(
            command,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL  # 입력도 차단하여 완전 독립
        )
        print(f"API 서버가 독립 프로세스 PID {api_server_process.pid}로 시작되었습니다.")

        # 독립 프로세스이므로 atexit 제거 (GUI 종료 시 서버는 계속 실행)

        # 서버가 준비될 때까지 대기
        return wait_for_server_ready()

    except Exception as e:
        print(f"API 서버 시작 실패: {e}")
        QMessageBox.critical(None, "치명적 오류", f"API 서버 시작에 실패했습니다.\n\n{e}")
        return False

def run_server_main():
    """'--run-server' 인자가 있을 때 uvicorn 서버를 실행하는 함수."""
    import signal
    import threading
    import logging
    from logging.handlers import RotatingFileHandler
    from sqlalchemy import text

    # PID 파일 및 로그 파일 경로 설정 (%APPDATA% 사용)
    app_data_dir = get_app_data_dir()
    data_dir = os.path.join(app_data_dir, "homework_helper_data")
    os.makedirs(data_dir, exist_ok=True)
    pid_file = os.path.join(data_dir, "db_server.pid")
    log_file = os.path.join(data_dir, "db_server.log")

    # 로깅 시스템 설정 (파일 기반, 순환 로그)
    logger = logging.getLogger('DBServer')
    logger.setLevel(logging.INFO)

    # 로그 포맷 설정
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 파일 핸들러 (최대 10MB, 5개 파일 유지)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 콘솔 핸들러 (개발 환경에서 확인용)
    if not getattr(sys, 'frozen', False):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.info("=" * 60)
    logger.info("서버 모드로 실행합니다.")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"로그 파일: {log_file}")
    logger.info(f"데이터 디렉토리: {data_dir}")

    # Windows Named Mutex 생성 (프로세스 유일성 보장)
    server_mutex = None
    if os.name == 'nt':
        try:
            import win32event
            import win32api
            mutex_name = "Global\\HomeworkHelperDBServerMutex"
            server_mutex = win32event.CreateMutex(None, False, mutex_name)
            if win32api.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                logger.error("서버가 이미 실행 중입니다! 중복 실행 불가.")
                sys.exit(1)
            logger.info(f"Windows Named Mutex 생성 완료: {mutex_name}")
        except ImportError:
            logger.warning("pywin32 없음: Named Mutex 사용 불가, PID 파일만 사용")
        except Exception as e:
            logger.error(f"Mutex 생성 실패: {e}")

    # PID 파일 생성 (Mutex와 함께 사용, fallback 용도)
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"PID 파일 생성: {pid_file}")
    except Exception as e:
        logger.error(f"PID 파일 생성 실패: {e}")

    # --- main.py의 내용을 여기로 통합 ---
    from fastapi import FastAPI, Depends, HTTPException
    from sqlalchemy.orm import Session
    import crud, models, schemas
    from database import SessionLocal, engine

    # 데이터베이스 무결성 확인 및 복구
    logger.info("데이터베이스 무결성 확인 중...")
    try:
        with engine.connect() as conn:
            # WAL 복구 체크포인트
            conn.execute(text("PRAGMA wal_checkpoint(RECOVER)"))
            conn.commit()

            # 무결성 검사
            result = conn.execute(text("PRAGMA integrity_check"))
            integrity_result = result.scalar()
            if integrity_result != "ok":
                logger.warning(f"데이터베이스 무결성 검사 실패: {integrity_result}")
            else:
                logger.info("데이터베이스 무결성 확인 완료.")
    except Exception as e:
        logger.error(f"데이터베이스 복구 중 오류: {e}", exc_info=True)

    # 데이터베이스 테이블 생성
    models.Base.metadata.create_all(bind=engine)

    # 주기적 WAL checkpoint 백그라운드 스레드
    def periodic_checkpoint(interval=60):
        """주기적으로 WAL checkpoint 수행"""
        while True:
            try:
                time.sleep(interval)
                with engine.connect() as conn:
                    conn.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
                    conn.commit()
                logger.info("WAL checkpoint 완료")
            except Exception as e:
                logger.error(f"Checkpoint 오류: {e}", exc_info=True)

    checkpoint_thread = threading.Thread(target=periodic_checkpoint, args=(60,), daemon=True)
    checkpoint_thread.start()
    logger.info("주기적 WAL checkpoint 스레드 시작 (60초 간격)")

    # Graceful shutdown 핸들러
    def shutdown_handler(signum, frame):
        """종료 신호 처리 - 안전하게 종료"""
        logger.info(f"서버 종료 신호 수신 (Signal: {signum}). 안전하게 종료합니다...")

        try:
            # 1. 최종 WAL checkpoint 수행
            logger.info("최종 WAL checkpoint 수행 중...")
            with engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                conn.commit()
            logger.info("WAL checkpoint 완료")

            # 2. 모든 데이터베이스 연결 종료
            engine.dispose()
            logger.info("데이터베이스 연결 종료")

            # 3. Mutex 해제 (프로세스 종료 시 자동 해제되지만 명시적으로 해제)
            if server_mutex and os.name == 'nt':
                try:
                    import win32api
                    win32api.CloseHandle(server_mutex)
                    logger.info("Windows Named Mutex 해제")
                except:
                    pass

            # 4. PID 파일 삭제
            if os.path.exists(pid_file):
                os.remove(pid_file)
                logger.info("PID 파일 삭제")
        except Exception as e:
            logger.error(f"종료 처리 중 오류: {e}", exc_info=True)

        logger.info("서버 종료 완료")
        logger.info("=" * 60)
        sys.exit(0)

    # Windows에서 Ctrl+C 처리
    if os.name == 'nt':
        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGBREAK, shutdown_handler)
        logger.info("종료 신호 핸들러 등록 완료 (SIGINT, SIGTERM, SIGBREAK)")

        # SetConsoleCtrlHandler로 시스템 종료 이벤트 처리
        try:
            import win32api
            def console_ctrl_handler(ctrl_type):
                """Windows 콘솔 제어 이벤트 처리"""
                if ctrl_type in (win32api.CTRL_C_EVENT, win32api.CTRL_BREAK_EVENT,
                                win32api.CTRL_CLOSE_EVENT, win32api.CTRL_LOGOFF_EVENT,
                                win32api.CTRL_SHUTDOWN_EVENT):
                    logger.info(f"Windows 시스템 종료 이벤트 감지 (Type: {ctrl_type})")
                    shutdown_handler(ctrl_type, None)
                    return True
                return False

            win32api.SetConsoleCtrlHandler(console_ctrl_handler, True)
            logger.info("Windows 시스템 종료 이벤트 핸들러 등록 완료")
        except ImportError:
            logger.warning("pywin32 없음: 시스템 종료 이벤트 처리 불가 (signal만 사용)")

    app = FastAPI()

    # Dependency
    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # create / read / update / delete [managed processes]
    @app.get("/processes", response_model=List[schemas.ProcessSchema])
    def get_all_processes(db: Session = Depends(get_db)):
        processes = crud.get_processes(db)
        return processes

    @app.get("/processes/{process_id}", response_model=schemas.ProcessSchema)
    def get_process_by_id(process_id: str, db: Session = Depends(get_db)):
        db_process = crud.get_process_by_id(db=db, process_id=process_id)
        if db_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return db_process

    @app.post("/processes", response_model=schemas.ProcessSchema, status_code=201)
    def create_new_process(process_data: schemas.ProcessCreateSchema, db: Session = Depends(get_db)):
        return crud.create_process(db = db, process = process_data)

    @app.put("/processes/{process_id}", response_model=schemas.ProcessSchema)
    def update_existing_process(process_id: str, process_data: schemas.ProcessCreateSchema, db: Session = Depends(get_db)):
        updated_process = crud.update_process(db = db, process_id = process_id, process = process_data)
        if updated_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return updated_process

    @app.delete("/processes/{process_id}")
    def delete_existing_process(process_id: str, db: Session = Depends(get_db)):
        deleted_process = crud.delete_process(db = db, process_id = process_id)
        if deleted_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return {"message": "프로세스가 삭제되었습니다."}

    # create / read / update / delete [web shortcuts]
    @app.get("/shortcuts", response_model=List[schemas.WebShortcutSchema])
    def get_all_shortcuts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        shortcuts = crud.get_shortcuts(db, skip=skip, limit=limit)
        return shortcuts

    @app.get("/shortcuts/{shortcut_id}", response_model=schemas.WebShortcutSchema)
    def get_shortcut_by_id(shortcut_id: str, db: Session = Depends(get_db)):
        db_shortcut = crud.get_shortcut_by_id(db, shortcut_id)
        if db_shortcut is None:
            raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
        return db_shortcut

    @app.post("/shortcuts", response_model=schemas.WebShortcutSchema, status_code=201)
    def create_new_shortcut(shortcut_data: schemas.WebShortcutCreate, db: Session = Depends(get_db)):
        return crud.create_shortcut(db = db, shortcut = shortcut_data)

    @app.put("/shortcuts/{shortcut_id}", response_model=schemas.WebShortcutSchema)
    def update_existing_shortcut(shortcut_id: str, shortcut_data: schemas.WebShortcutCreate, db: Session = Depends(get_db)):
        updated_shortcut = crud.update_shortcut(db = db, shortcut_id = shortcut_id, shortcut = shortcut_data)
        if updated_shortcut is None:
            raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
        return updated_shortcut

    @app.delete("/shortcuts/{shortcut_id}")
    def delete_existing_shortcut(shortcut_id: str, db: Session = Depends(get_db)):
        deleted_shortcut = crud.delete_shortcut(db = db, shortcut_id = shortcut_id)
        if deleted_shortcut is None:
            raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
        return {"message": "웹 바로 가기가 삭제되었습니다."}

    # read / update [global settings]
    @app.get("/settings", response_model=schemas.GlobalSettingsSchema)
    def get_global_settings(db: Session = Depends(get_db)):
        return crud.get_settings(db)

    @app.put("/settings", response_model=schemas.GlobalSettingsSchema)
    def update_global_settings(settings_data: schemas.GlobalSettingsSchema, db: Session = Depends(get_db)):
        return crud.update_settings(db = db, settings = settings_data)

    # create / read / update [process sessions]
    @app.post("/sessions", response_model=schemas.ProcessSessionSchema, status_code=201)
    def create_new_session(session_data: schemas.ProcessSessionCreate, db: Session = Depends(get_db)):
        """새로운 프로세스 세션 시작"""
        return crud.create_session(db=db, session=session_data)

    @app.put("/sessions/{session_id}/end", response_model=schemas.ProcessSessionSchema)
    def end_process_session(session_id: int, end_data: schemas.ProcessSessionUpdate, db: Session = Depends(get_db)):
        """프로세스 세션 종료"""
        ended_session = crud.end_session(db=db, session_id=session_id, end_timestamp=end_data.end_timestamp)
        if ended_session is None:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        return ended_session

    @app.get("/sessions/process/{process_id}", response_model=List[schemas.ProcessSessionSchema])
    def get_sessions_by_process(process_id: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        """특정 프로세스의 세션 이력 조회"""
        return crud.get_sessions_by_process_id(db=db, process_id=process_id, skip=skip, limit=limit)

    @app.get("/sessions/process/{process_id}/active", response_model=schemas.ProcessSessionSchema)
    def get_active_session(process_id: str, db: Session = Depends(get_db)):
        """특정 프로세스의 현재 활성 세션 조회"""
        session = crud.get_active_session_by_process_id(db=db, process_id=process_id)
        if session is None:
            raise HTTPException(status_code=404, detail="활성 세션이 없습니다.")
        return session

    @app.get("/sessions", response_model=List[schemas.ProcessSessionSchema])
    def get_all_sessions_list(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        """모든 세션 조회"""
        return crud.get_all_sessions(db=db, skip=skip, limit=limit)

    # ==================== Graceful Shutdown API ====================
    from fastapi import BackgroundTasks

    @app.post("/shutdown")
    async def shutdown_server(background_tasks: BackgroundTasks):
        """
        서버를 안전하게 종료합니다.
        1. DB 체크포인트 수행 (.wal → .db)
        2. DB 연결 정리
        3. 서버 프로세스 종료
        """

        def perform_graceful_shutdown():
            print("=== Graceful Shutdown 시작 ===")

            # 1. 데이터베이스 WAL 체크포인트 실행 (가장 중요!)
            try:
                from database import engine
                from sqlalchemy import text
                with engine.connect() as conn:
                    # TRUNCATE: WAL 파일의 모든 내용을 .db에 기록하고 WAL 파일을 삭제
                    conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE);"))
                    conn.commit()
                print("✓ WAL 체크포인트 완료 (.wal → .db 이동)")
            except Exception as e:
                print(f"WAL 체크포인트 경고 (무시 가능): {e}")

            # 2. 데이터베이스 엔진 정리
            try:
                from database import engine
                engine.dispose()
                print("✓ 데이터베이스 엔진 정리 완료")
            except Exception as e:
                print(f"엔진 정리 경고: {e}")

            # 3. uvicorn 서버 종료
            # Windows에서 SIGTERM은 강제 종료로 동작하므로, sys.exit() 사용
            # 이미 등록된 shutdown_handler가 정리 작업을 수행했으므로 안전하게 종료
            print("✓ 서버 종료 신호 전송")
            import sys
            sys.exit(0)

        # 백그라운드에서 종료 작업 수행 (응답은 즉시 반환)
        background_tasks.add_task(perform_graceful_shutdown)
        return {"status": "shutting_down"}
    # ===============================================================

    import uvicorn
    # uvicorn.run에 문자열 대신 app 객체를 직접 전달합니다.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

def stop_api_server():
    """
    독립 프로세스로 실행된 API 서버를 종료합니다.
    주의: 이 함수는 더 이상 자동으로 호출되지 않습니다.
    서버는 독립적으로 실행되며, 사용자가 수동으로 종료하거나 시스템 종료 시 graceful shutdown됩니다.
    """
    global api_server_process
    if api_server_process:
        print(f"API 서버(PID: {api_server_process.pid})는 독립 프로세스로 계속 실행됩니다.")
        # 더 이상 서버를 종료하지 않음
        # api_server_process.terminate()
        # api_server_process.wait()

def start_main_application(instance_manager: SingleInstanceApplication):
    """메인 애플리케이션을 설정하고 실행합니다."""
    app = QApplication(sys.argv)
    app.setApplicationName("숙제 관리자") # 애플리케이션 이름 설정
    app.setOrganizationName("HomeworkHelperOrg") # 조직 이름 설정 (설정 파일 경로 등에 사용될 수 있음)

    # 마이그레이션 로직을 QApplication 생성 직후로 이동
    run_automatic_migration()

    # 현재 관리자 권한 상태 로그
    if os.name == 'nt':
        admin_status = "관리자 권한으로 실행 중" if is_admin() else "일반 사용자 권한으로 실행 중"
        print(f"현재 실행 상태: {admin_status}")

    # --- 폰트 설정 ---
    font_path_ttf = get_bundle_resource_path(r"font\NEXONLv1GothicOTFBold.otf")
    if os.path.exists(font_path_ttf):
        font_id = QFontDatabase.addApplicationFont(font_path_ttf)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            app.setFont(QFont(font_family, 10))
            print(f"폰트 로드 성공: {font_family}")
        else:
            print("폰트 로드 실패: QFontDatabase.addApplicationFont()가 -1을 반환했습니다.")
    else:
        print(f"폰트 파일 없음: {font_path_ttf}")
    
    app.setQuitOnLastWindowClosed(False) # 마지막 창이 닫혀도 애플리케이션 종료되지 않도록 설정 (트레이 아이콘 사용 시 필수)

    # 데이터 저장 폴더 경로 설정
    data_folder_name = "homework_helper_data"
    if getattr(sys, 'frozen', False): # PyInstaller 등으로 패키징된 경우
        application_path = os.path.dirname(sys.executable)
    else: # 일반 파이썬 스크립트로 실행된 경우
        application_path = os.path.dirname(os.path.abspath(__file__))
    # data_path = os.path.join(application_path, data_folder_name)
    # data_manager_instance = DataManager(data_folder=data_path) # 데이터 매니저 생성
    api_client_instance = ApiClient() # API 클라이언트 생성 (기본 URL: http://127.0.0.1:8000)
    

    # 메인 윈도우 생성 (인스턴스 매니저 전달)
    main_window = MainWindow(api_client_instance, instance_manager=instance_manager)
    # IPC 서버 시작 (다른 인스턴스로부터의 활성화 요청 처리용)
    instance_manager.start_ipc_server(main_window_to_activate=main_window)
    main_window.show() # 메인 윈도우 표시
    exit_code = app.exec() # 애플리케이션 이벤트 루프 시작
    sys.exit(exit_code) # 종료 코드로 시스템 종료

if __name__ == "__main__":
    # 패키징된 .exe가 '--run-server' 인자와 함께 실행되면 서버만 구동
    if getattr(sys, 'frozen', False) and "--run-server" in sys.argv:
        run_server_main()
    else:
        # 일반 GUI 애플리케이션 실행
        check_admin_requirement()
        
        # API 서버 시작 및 준비 확인
        if not start_api_server():
            # 서버 시작 실패 시 프로그램 종료
            sys.exit(1)

        # 단일 인스턴스 실행 확인 로직을 통해 애플리케이션 시작
        run_with_single_instance_check(
            application_name="숙제 관리자",
            main_app_start_callback=start_main_application
        )
