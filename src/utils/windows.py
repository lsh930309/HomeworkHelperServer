# windows_utils.py
import winreg
import sys
import os
import winshell
from typing import Optional

APP_REGISTRY_NAME = "GameCycleHelper" # 레지스트리에 등록될 프로그램 이름
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

def is_windows() -> bool:
    return os.name == 'nt'

def get_script_and_interpreter_path() -> tuple[Optional[str], Optional[str]]:
    """ 현재 스크립트의 절대 경로와 사용할 인터프리터 경로를 반환합니다. """
    try:
        script_path = os.path.abspath(sys.argv[0])
        
        # .pyw로 실행될 것을 가정하고 pythonw.exe 경로를 우선적으로 찾음
        interpreter_dir = os.path.dirname(sys.executable)
        pythonw_exe_path = os.path.join(interpreter_dir, "pythonw.exe")
        
        if os.path.exists(pythonw_exe_path):
            interpreter_path = pythonw_exe_path
        else: # pythonw.exe를 못 찾으면 현재 인터프리터 사용 (주로 python.exe)
            interpreter_path = sys.executable
            print("경고: pythonw.exe를 찾지 못했습니다. 콘솔 창이 나타날 수 있습니다.")
            
        # 경로에 공백이 있을 수 있으므로 따옴표로 감싸기
        return f'"{interpreter_path}"', f'"{script_path}"'
    except Exception as e:
        print(f"스크립트 또는 인터프리터 경로를 가져오는 중 오류: {e}")
        return None, None

def set_startup_registry(enable: bool) -> bool:
    """ Windows 시작 시 자동 실행을 위해 레지스트리를 설정/해제합니다. """
    if not is_windows():
        print("Windows 환경이 아니므로 시작 프로그램 등록을 건너뜁니다.")
        return False

    interpreter_path_quoted, script_path_quoted = get_script_and_interpreter_path()
    if not script_path_quoted or not interpreter_path_quoted:
        print("자동 실행 경로를 구성할 수 없습니다.")
        return False

    command_to_run = f"{interpreter_path_quoted} {script_path_quoted}"

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            winreg.SetValueEx(key, APP_REGISTRY_NAME, 0, winreg.REG_SZ, command_to_run)
            print(f"'{APP_REGISTRY_NAME}'을(를) 시작 프로그램에 등록했습니다: {command_to_run}")
        else:
            try:
                winreg.DeleteValue(key, APP_REGISTRY_NAME)
                print(f"'{APP_REGISTRY_NAME}'을(를) 시작 프로그램에서 제거했습니다.")
            except FileNotFoundError:
                print(f"'{APP_REGISTRY_NAME}'이(가) 시작 프로그램에 등록되어 있지 않습니다.")
                pass # 이미 없으면 문제 없음
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"시작 프로그램 레지스트리 설정 중 오류: {e}")
        return False

def get_startup_registry_status() -> bool:
    """ 현재 자동 실행 레지스트리 등록 상태를 확인합니다. """
    if not is_windows():
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_REGISTRY_NAME)
        winreg.CloseKey(key)
        return True # 값이 존재하면 True
    except FileNotFoundError:
        return False # 값이 없으면 False
    except Exception as e:
        print(f"시작 프로그램 상태 확인 중 오류: {e}")
        return False

def get_startup_folder_path() -> Optional[str]:
    """ Windows 시작 프로그램 폴더 경로를 반환합니다. """
    if not is_windows():
        return None
    try:
        # shell:startup 명령어로 열리는 폴더 경로
        startup_path = winshell.startup()
        print(f"시작 프로그램 폴더 경로: {startup_path}")
        return startup_path
    except Exception as e:
        print(f"시작 프로그램 폴더 경로를 가져오는 중 오류: {e}")
        # 대체 방법: 환경 변수를 사용한 경로
        try:
            appdata = os.environ.get('APPDATA')
            if appdata:
                startup_path = os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup")
                print(f"대체 시작 프로그램 폴더 경로: {startup_path}")
                return startup_path
        except Exception as e2:
            print(f"대체 경로 생성 중 오류: {e2}")
        return None

def set_startup_shortcut(enable: bool) -> bool:
    """ Windows 시작 시 자동 실행을 위해 바로가기 파일을 생성/삭제합니다. """
    print(f"set_startup_shortcut 호출됨 - enable: {enable}")
    if not is_windows():
        print("Windows 환경이 아니므로 시작 프로그램 등록을 건너뜁니다.")
        return False

    startup_folder = get_startup_folder_path()
    if not startup_folder:
        print("시작 프로그램 폴더 경로를 찾을 수 없습니다.")
        return False

    shortcut_name = f"{APP_REGISTRY_NAME}.lnk"
    shortcut_path = os.path.join(startup_folder, shortcut_name)
    
    print(f"바로가기 파일 경로: {shortcut_path}")

    try:
        if enable:
            # 바로가기 생성
            interpreter_path, script_path = get_script_and_interpreter_path()
            if not script_path or not interpreter_path:
                print("자동 실행 경로를 구성할 수 없습니다.")
                return False

            # 따옴표 제거 (winshell은 따옴표 없이 경로를 받음)
            interpreter_path = interpreter_path.strip('"')
            script_path = script_path.strip('"')
            
            print(f"인터프리터 경로: {interpreter_path}")
            print(f"스크립트 경로: {script_path}")

            from win32com.client import Dispatch
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = interpreter_path
            shortcut.Arguments = script_path
            shortcut.WorkingDirectory = os.path.dirname(script_path)
            shortcut.IconLocation = script_path
            shortcut.save()
            
            print(f"'{APP_REGISTRY_NAME}' 바로가기를 시작 프로그램에 생성했습니다: {shortcut_path}")
            print(f"바로가기 파일이 실제로 생성되었는지 확인: {os.path.exists(shortcut_path)}")
        else:
            # 바로가기 삭제
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
                print(f"'{APP_REGISTRY_NAME}' 바로가기를 시작 프로그램에서 제거했습니다.")
            else:
                print(f"'{APP_REGISTRY_NAME}' 바로가기가 시작 프로그램에 존재하지 않습니다.")
        
        return True
    except Exception as e:
        print(f"시작 프로그램 바로가기 설정 중 오류: {e}")
        return False

def get_startup_shortcut_status() -> bool:
    """ 현재 자동 실행 바로가기 등록 상태를 확인합니다. """
    if not is_windows():
        return False
    
    startup_folder = get_startup_folder_path()
    if not startup_folder:
        return False
    
    shortcut_name = f"{APP_REGISTRY_NAME}.lnk"
    shortcut_path = os.path.join(startup_folder, shortcut_name)
    
    return os.path.exists(shortcut_path)