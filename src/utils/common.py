# utils.py
import sys
import os
import shutil
from typing import Optional

# --- 추가: 실행 파일 기준 경로 반환 함수 ---
def get_base_path() -> str:
    """PyInstaller 환경이면 실행 파일 위치, 아니면 프로젝트 루트 추정(이 파일의 상위 디렉토리)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # 개발 환경: 현재 파일이 프로젝트 루트 하위라고 가정하고 한 단계만 올라감
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "."))

def resource_path(relative_path):
    """ 개발 환경 및 PyInstaller 환경 모두에서 리소스 파일의 절대 경로를 반환합니다. """
    return os.path.join(get_base_path(), relative_path)

def get_bundle_resource_path(relative_path: str) -> str:
    """PyInstaller면 _MEIPASS, 아니면 get_base_path() 기준."""
    base_path = getattr(sys, "_MEIPASS", None)
    if not base_path:
        base_path = get_base_path()
    return os.path.join(base_path, relative_path)

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

def get_shortcuts_directory() -> str:
    """homework_helper_data/shortcuts 디렉토리 경로를 반환합니다. (%APPDATA% 사용)"""
    app_data_dir = get_app_data_dir()
    shortcuts_dir = os.path.join(app_data_dir, "homework_helper_data", "shortcuts")
    return os.path.abspath(shortcuts_dir)

def ensure_shortcuts_directory() -> bool:
    """shortcuts 디렉토리가 존재하는지 확인하고, 없으면 생성합니다."""
    shortcuts_dir = get_shortcuts_directory()
    try:
        if not os.path.exists(shortcuts_dir):
            os.makedirs(shortcuts_dir, exist_ok=True)
        return True
    except Exception as e:
        print(f"shortcuts 디렉토리 생성 실패: {e}")
        return False

def copy_shortcut_file(source_path: str, process_id: Optional[str] = None) -> Optional[str]:
    """
    바로가기 파일을 shortcuts 디렉토리에 복사하고 복사된 경로를 반환합니다.
    
    Args:
        source_path: 원본 바로가기 파일 경로
        process_id: 프로세스 ID (제공 시 해당 ID로 파일명 고정, 덮어쓰기 방식)
    
    Returns:
        복사된 파일 경로 또는 None
    """
    if not os.path.exists(source_path):
        print(f"원본 파일이 존재하지 않습니다: {source_path}")
        return None
    
    # 파일 확장자 확인
    file_ext = os.path.splitext(source_path)[1].lower()
    if file_ext not in ['.lnk', '.url', '.exe', '.bat', '.cmd']:
        print(f"지원하지 않는 파일 형식입니다: {file_ext}")
        return None
    
    # shortcuts 디렉토리 확인/생성
    if not ensure_shortcuts_directory():
        return None
    
    shortcuts_dir = get_shortcuts_directory()
    
    # 원본 파일명 가져오기
    original_filename = os.path.basename(source_path)
    name, ext = os.path.splitext(original_filename)
    
    if process_id:
        # 프로세스 ID 제공 시: 고정 파일명 사용 (덮어쓰기)
        new_filename = f"{process_id}{ext}"
        new_path = os.path.join(shortcuts_dir, new_filename)
        
        # 기존 파일이 있으면 삭제 후 복사 (갱신)
        if os.path.exists(new_path):
            try:
                os.remove(new_path)
                print(f"기존 바로가기 파일 삭제: {new_path}")
            except Exception as e:
                print(f"기존 바로가기 파일 삭제 실패: {e}")
    else:
        # 프로세스 ID 미제공 시: 기존 방식 (중복 방지 카운터)
        counter = 1
        new_filename = original_filename
        new_path = os.path.join(shortcuts_dir, new_filename)
        
        while os.path.exists(new_path):
            new_filename = f"{name}_{counter}{ext}"
            new_path = os.path.join(shortcuts_dir, new_filename)
            counter += 1
    
    try:
        # 파일 복사
        shutil.copy2(source_path, new_path)
        print(f"바로가기 파일 복사 완료: {source_path} → {new_path}")
        return new_path
    except Exception as e:
        print(f"바로가기 파일 복사 실패: {e}")
        return None