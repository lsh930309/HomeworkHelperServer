# migration.py
"""JSON 데이터를 SQLite DB로 마이그레이션하는 모듈"""

import sys
import os
import datetime
from PyQt6.QtWidgets import QApplication, QMessageBox


def run_automatic_migration():
    """
    애플리케이션 시작 시 자동으로 JSON 데이터를 SQLite DB로 마이그레이션합니다.
    성공 시 .migration_done 파일을 생성하여 중복 실행을 방지합니다.
    """
    print("자동 마이그레이션 필요 여부 확인...")

    # 데이터 경로 및 마이그레이션 완료 플래그 파일 경로 설정 (원래 로직으로 복구)
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    data_path = os.path.join(base_path, "homework_helper_data")
    migration_flag_path = os.path.join(data_path, ".migration_done")

    # 데이터 폴더가 없으면 새로 생성합니다.
    if not os.path.exists(data_path):
        os.makedirs(data_path)

    # 마이그레이션이 이미 완료되었으면 함수 종료
    if os.path.exists(migration_flag_path):
        print("마이그레이션이 이미 완료되었습니다. 건너뜁니다.")
        return

    # 구 버전의 핵심 데이터 파일이 있는지 확인
    old_process_file = os.path.join(data_path, "managed_processes.json")
    if not os.path.exists(old_process_file):
        print("구 버전 데이터 파일이 없어 마이그레이션이 필요하지 않습니다.")
        with open(migration_flag_path, 'w', encoding='utf-8') as f:
            f.write(datetime.datetime.now().isoformat())
        return

    # --- 마이그레이션 실행 ---
    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.information(None, "데이터 업그레이드",
                              "데이터를 최신 버전으로 안전하게 업그레이드합니다.\n"
                              "잠시만 기다려주세요...")

    try:
        # DB와 데이터 로직 모듈 임포트
        import crud
        import schemas
        from data_manager import DataManager
        from database import SessionLocal
        # DB 테이블이 아직 생성되지 않았을 수 있으므로, 마이그레이션 전에 명시적으로 생성 보장
        import models
        from database import engine
        models.Base.metadata.create_all(bind=engine)

        db = SessionLocal()
        local_data_manager = DataManager(data_folder=data_path)

        # 1. ManagedProcess 마이그레이션 (업서트)
        for p in local_data_manager.managed_processes:
            existing = crud.get_process_by_id(db, p.id)
            p_schema = schemas.ProcessCreateSchema(**p.to_dict())
            if existing:
                crud.update_process(db, p.id, p_schema)
            else:
                crud.create_process(db, p_schema)

        # 2. WebShortcut 마이그레이션 (업서트)
        for sc in local_data_manager.web_shortcuts:
            existing_sc = crud.get_shortcut_by_id(db, sc.id)
            sc_schema = schemas.WebShortcutCreate(**sc.to_dict())
            if existing_sc:
                crud.update_shortcut(db, sc.id, sc_schema)
            else:
                crud.create_shortcut(db, sc_schema)

        # 3. GlobalSettings 마이그레이션 (업데이트)
        gs_schema = schemas.GlobalSettingsSchema(**local_data_manager.global_settings.to_dict())
        crud.update_settings(db, gs_schema)

        db.close()

        # 성공 시 플래그 파일 생성
        with open(migration_flag_path, 'w', encoding='utf-8') as f:
            f.write(datetime.datetime.now().isoformat())

        QMessageBox.information(None, "업그레이드 완료", "데이터 업그레이드가 성공적으로 완료되었습니다.")

        # --- 데이터 정리 ---
        print("기존 JSON 데이터 파일을 백업합니다...")
        for filename in ["managed_processes.json", "web_shortcuts.json", "global_settings.json"]:
            old_file = os.path.join(data_path, filename)
            if os.path.exists(old_file):
                backup_file = old_file + ".bak"
                os.rename(old_file, backup_file)
                print(f"'{filename}' -> '{filename}.bak'")

    except Exception as e:
        print(f"마이그레이션 중 심각한 오류 발생: {e}")
        QMessageBox.critical(None, "업그레이드 실패",
                               f"데이터 업그레이드 중 오류가 발생했습니다.\n\n{e}\n\n"
                               "프로그램을 종료합니다. 개발자에게 문의해주세요.")
        sys.exit(1)
