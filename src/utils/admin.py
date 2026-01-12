# admin_utils.py
"""Windows 관리자 권한 관련 유틸리티 함수들"""

import sys
import os
import ctypes


def is_admin():
    """현재 프로세스가 관리자 권한으로 실행되고 있는지 확인합니다."""
    if not os.name == 'nt':
        return False

    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin():
    """현재 스크립트를 관리자 권한으로 재시작합니다."""
    if not os.name == 'nt':
        return False

    try:
        if getattr(sys, 'frozen', False):
            # PyInstaller로 패키징된 경우
            script = sys.executable
        else:
            # 일반 파이썬 스크립트인 경우
            script = sys.argv[0]

        # 명령줄 인수를 문자열로 결합 (sys.argv[1:]부터 전달)
        params = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in sys.argv[1:])

        # ShellExecuteW를 사용하여 관리자 권한으로 재시작
        shell32 = ctypes.windll.shell32
        ret = shell32.ShellExecuteW(None, "runas", script, params if params else None, None, 1)

        if ret > 32:
            print("관리자 권한으로 재시작을 요청했습니다.")
            return True
        else:
            print(f"관리자 권한으로 재시작 요청 실패. 오류 코드: {ret}")
            return False
    except Exception as e:
        print(f"관리자 권한으로 재시작 중 오류 발생: {e}")
        return False


def restart_as_normal():
    """현재 스크립트를 일반 권한으로 재시작합니다 (관리자→일반 전환용)."""
    if not os.name == 'nt':
        return False

    try:
        import subprocess
        
        if getattr(sys, 'frozen', False):
            # PyInstaller로 패키징된 경우
            script = sys.executable
            args = [script] + sys.argv[1:]
        else:
            # 일반 파이썬 스크립트인 경우
            script = sys.executable
            args = [script, sys.argv[0]] + sys.argv[1:]

        # 새 프로세스를 일반 권한으로 시작 (현재 프로세스와 분리)
        subprocess.Popen(
            args,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        print("일반 권한으로 재시작을 요청했습니다.")
        return True
    except Exception as e:
        print(f"일반 권한으로 재시작 중 오류 발생: {e}")
        return False


def check_admin_requirement():
    """관리자 권한이 필요한지 확인하고, 필요시 자동으로 재시작합니다."""
    if not os.name == 'nt':
        print("[DEBUG] Windows가 아닌 환경입니다. 관리자 권한 체크를 건너뜁니다.")
        return False

    # SQLite 데이터베이스에서 글로벌 설정을 직접 읽어 관리자 권한 실행 설정을 확인
    try:
        # %APPDATA% 기반 경로 사용 (homework_helper.pyw의 get_app_data_dir()와 동일한 로직)
        # onedir 빌드에서 sys.executable은 Program Files를 가리키므로 사용하지 않음!
        app_data = os.getenv('APPDATA')
        if not app_data:
            app_data = os.path.expanduser('~')
            print(f"[DEBUG] APPDATA 환경변수가 없어 홈 디렉토리 사용: {app_data}")

        app_dir = os.path.join(app_data, 'HomeworkHelper')
        data_folder = os.path.join(app_dir, "homework_helper_data")
        db_path = os.path.join(data_folder, "app_data.db")

        print(f"[DEBUG] APPDATA 기반 경로 사용: {app_data}")

        print(f"[DEBUG] 데이터베이스 경로: {db_path}")
        print(f"[DEBUG] 데이터베이스 존재 여부: {os.path.exists(db_path)}")

        if os.path.exists(db_path):
            # SQLite 데이터베이스에서 직접 설정 읽기
            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # global_settings 테이블에서 run_as_admin 값 가져오기 (id=1인 행)
            cursor.execute("SELECT run_as_admin FROM global_settings WHERE id = 1")
            result = cursor.fetchone()
            conn.close()

            if result:
                run_as_admin_setting = bool(result[0])
                print(f"[DEBUG] run_as_admin 설정 값: {run_as_admin_setting}")
                print(f"[DEBUG] 현재 관리자 권한 여부: {is_admin()}")

                if run_as_admin_setting and not is_admin():
                    print("글로벌 설정에서 관리자 권한으로 실행이 활성화되어 있습니다.")
                    print("관리자 권한으로 재시작을 시도합니다...")
                    if run_as_admin():
                        sys.exit(0)  # 현재 인스턴스 종료
                    else:
                        print("관리자 권한으로 재시작에 실패했습니다. 일반 권한으로 계속 실행합니다.")
                        return False
                else:
                    print(f"[DEBUG] 관리자 권한으로 재시작 불필요 (설정: {run_as_admin_setting}, 현재 관리자: {is_admin()})")
            else:
                print("[DEBUG] 데이터베이스에 설정 정보가 없습니다.")
        else:
            print("[DEBUG] 데이터베이스 파일이 존재하지 않습니다.")
    except Exception as e:
        print(f"관리자 권한 설정 확인 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    return False
