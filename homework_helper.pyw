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

def start_api_server() -> bool:
    """FastAPI 서버를 서브프로세스로 실행합니다."""
    global api_server_process
    try:
        if getattr(sys, 'frozen', False):
            # 패키지 환경: 자기 자신(.exe)을 '--run-server' 인자와 함께 실행
            command = [sys.executable, "--run-server"]
        else:
            # 개발 환경: uvicorn을 직접 실행
            command = [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]

        print(f"API 서버 실행 명령어: {' '.join(command)}")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        
        # CREATE_NO_WINDOW 사용 시 stdout/stderr이 None이 되어 uvicorn 로깅 설정에서 오류 발생
        # 이를 방지하기 위해 stdout과 stderr를 DEVNULL로 리디렉션합니다.
        api_server_process = subprocess.Popen(
            command, creationflags=creationflags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        print(f"API 서버가 PID {api_server_process.pid}로 시작되었습니다.")
        
        # 프로그램 종료 시 서버도 함께 종료되도록 등록
        atexit.register(stop_api_server)

        # 서버가 준비될 때까지 대기 (최대 10초)
        print("API 서버 준비 대기 중...")
        import requests
        base_url = "http://127.0.0.1:8000"
        for i in range(50): # 0.2초 * 50 = 10초
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

    except Exception as e:
        print(f"API 서버 시작 실패: {e}")
        QMessageBox.critical(None, "치명적 오류", f"API 서버 시작에 실패했습니다.\n\n{e}")
        return False

def run_server_main():
    """'--run-server' 인자가 있을 때 uvicorn 서버를 실행하는 함수."""
    print("서버 모드로 실행합니다.")
    # --- main.py의 내용을 여기로 통합 ---
    from fastapi import FastAPI, Depends, HTTPException
    from sqlalchemy.orm import Session
    import crud, models, schemas
    from database import SessionLocal, engine

    # 데이터베이스 테이블 생성
    models.Base.metadata.create_all(bind=engine)

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

    import uvicorn
    # uvicorn.run에 문자열 대신 app 객체를 직접 전달합니다.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

def stop_api_server():
    """실행 중인 API 서버 서브프로세스를 종료합니다."""
    global api_server_process
    if api_server_process:
        print(f"API 서버(PID: {api_server_process.pid})를 종료합니다.")
        api_server_process.terminate()
        api_server_process.wait()

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
