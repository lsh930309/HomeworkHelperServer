# admin_utils.py
"""Windows 관리자 권한 관련 유틸리티 함수들"""

import sys
import os
import subprocess
import ctypes

# 설치 시 등록되는 예약 작업 이름 (installer.iss와 반드시 일치해야 함)
_ADMIN_TASK_NAME = "HomeworkHelper_Admin"
_NORMAL_TASK_NAME = "HomeworkHelper_Normal"


def is_admin():
    """현재 프로세스가 관리자 권한으로 실행되고 있는지 확인합니다."""
    if not os.name == 'nt':
        return False

    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin():
    """관리자 권한으로 재시작합니다.

    설치 시 등록된 예약 작업(HomeworkHelper_Admin)을 통해 UAC 프롬프트 없이
    관리자 권한으로 재시작합니다.
    예약 작업이 없는 경우(개발 환경 등) ShellExecuteW 방식으로 fallback합니다.
    """
    if not os.name == 'nt':
        return False

    try:
        result = subprocess.run(
            ['schtasks', '/run', '/tn', _ADMIN_TASK_NAME],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"예약 작업 '{_ADMIN_TASK_NAME}'을 통해 관리자 권한으로 재시작 요청됨.")
            return True
        else:
            stderr = result.stderr.decode('utf-8', errors='replace').strip()
            print(f"예약 작업 실행 실패 (code={result.returncode}): {stderr}")
            print("ShellExecuteW fallback으로 전환합니다...")
            return _run_as_admin_shellexecute()
    except Exception as e:
        print(f"예약 작업 실행 오류: {e}, ShellExecuteW fallback으로 전환합니다...")
        return _run_as_admin_shellexecute()


def _run_as_admin_shellexecute():
    """예약 작업이 없을 때 ShellExecuteW('runas') 방식으로 fallback합니다.

    개발 환경 또는 인스톨러 없이 실행할 때 사용됩니다.
    이 경우 UAC 프롬프트가 표시됩니다.
    """
    try:
        if getattr(sys, 'frozen', False):
            script = sys.executable
        else:
            script = sys.argv[0]

        params = subprocess.list2cmdline(sys.argv[1:])

        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", script, params if params else None, None, 1
        )
        if ret > 32:
            print("ShellExecuteW fallback: 관리자 권한 재시작 요청됨.")
            return True
        else:
            print(f"ShellExecuteW fallback 실패. 오류 코드: {ret}")
            return False
    except Exception as e:
        print(f"ShellExecuteW fallback 오류: {e}")
        return False


def restart_as_normal():
    """일반 권한으로 재시작합니다 (관리자 → 일반 전환용).

    설치 시 등록된 예약 작업(HomeworkHelper_Normal)을 통해 재시작합니다.
    Task Scheduler는 작업 소유자의 기본(비상승) 토큰으로 프로세스를 시작하므로
    관리자 → 일반 권한 전환이 정확하게 이루어집니다.
    예약 작업이 없는 경우 subprocess 방식으로 fallback합니다.
    """
    if not os.name == 'nt':
        return False

    try:
        result = subprocess.run(
            ['schtasks', '/run', '/tn', _NORMAL_TASK_NAME],
            capture_output=True,
            timeout=10
        )
        if result.returncode == 0:
            print(f"예약 작업 '{_NORMAL_TASK_NAME}'을 통해 일반 권한으로 재시작 요청됨.")
            return True
        else:
            stderr = result.stderr.decode('utf-8', errors='replace').strip()
            print(f"예약 작업 실행 실패 (code={result.returncode}): {stderr}")
            print("subprocess fallback으로 전환합니다...")
            return _restart_as_normal_subprocess()
    except Exception as e:
        print(f"예약 작업 실행 오류: {e}, subprocess fallback으로 전환합니다...")
        return _restart_as_normal_subprocess()


def _restart_as_normal_subprocess():
    """예약 작업이 없을 때 subprocess 방식으로 fallback합니다.

    개발 환경 또는 인스톨러 없이 실행할 때 사용됩니다.
    주의: 이 방식은 부모 프로세스의 토큰을 상속하므로
    관리자 권한으로 실행 중일 경우 자식 프로세스도 관리자 권한을 가질 수 있습니다.
    """
    try:
        if getattr(sys, 'frozen', False):
            args = [sys.executable, *sys.argv[1:]]
        else:
            args = [sys.executable, sys.argv[0], *sys.argv[1:]]

        subprocess.Popen(
            args,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
        print("subprocess fallback: 일반 권한 재시작 요청됨.")
        return True
    except Exception as e:
        print(f"subprocess fallback 오류: {e}")
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
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()

                # global_settings 테이블에서 run_as_admin 값 가져오기 (id=1인 행)
                cursor.execute("SELECT run_as_admin FROM global_settings WHERE id = 1")
                result = cursor.fetchone()

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
