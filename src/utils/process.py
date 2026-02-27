# process_utils.py
import psutil
from typing import List, Dict, Any, Optional
import os
import sys
import hashlib
import configparser
from PyQt6.QtWidgets import QFileIconProvider # 아이콘 제공자
from PyQt6.QtCore import QFileInfo          # 파일 정보 객체
from PyQt6.QtGui import QIcon, QPixmap

# QFileIconProvider는 애플리케이션 컨텍스트에서 생성되는 것이 좋을 수 있으나,
# 여기서 간단히 사용하기 위해 전역 또는 함수 내 지역 변수로 생성합니다.
# 앱 전체에서 하나의 인스턴스를 공유하는 것이 더 효율적일 수 있습니다.
# 여기서는 함수 호출 시마다 생성 (간단한 접근)
# icon_provider = QFileIconProvider() # 전역으로 두거나, GUI 클래스 멤버로 전달 가능


def get_user_scale_factor() -> float:
    """
    사용자 지정 UI 배율을 반환합니다.
    homework_helper.pyw의 get_user_scale_factor()와 동일한 로직.

    Returns:
        float: 배율 (예: 1.0, 1.25, 1.5, 1.75, 2.0)
    """
    try:
        if sys.platform == "win32":
            app_data = os.getenv('APPDATA', os.path.expanduser('~'))
        else:
            app_data = os.path.expanduser('~/.config')

        config_path = os.path.join(app_data, 'HomeworkHelper', 'display_settings.ini')

        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            scale_percent = config.getint('Display', 'scale_percent', fallback=100)
            return scale_percent / 100.0
    except Exception:
        pass

    return 1.0  # 기본값 100%

def get_qicon_for_file(file_path: Optional[str], icon_size: int = 24) -> Optional[Any]: # 반환 타입을 Any로 (QIcon)
    """
    주어진 파일 경로에 대한 고화질 QIcon 객체를 반환합니다. 실패 시 None.

    대시보드의 고해상도 아이콘 추출 로직을 사용하여 선명한 아이콘을 제공합니다.
    사용자 지정 UI 배율에 맞춰 실제 표시 크기보다 큰 이미지를 로드합니다.

    Args:
        file_path: 실행 파일 경로
        icon_size: 기준 아이콘 크기 (기본 24px, 사용자 배율에 따라 자동 조정)

    Returns:
        QIcon 객체 또는 None
    """
    if not file_path or not os.path.exists(file_path): # 파일이 존재해야 아이콘을 가져올 수 있음
        return None

    try:
        from PyQt6.QtCore import Qt
        # 고해상도 아이콘 추출 시도 (대시보드 로직 활용)
        from src.api.dashboard.icons import extract_icon_from_exe, get_icon_for_size

        # 파일 경로 기반 고유 ID 생성
        process_id = hashlib.md5(os.path.normcase(os.path.abspath(file_path)).encode()).hexdigest()

        # 아이콘 추출 (캐시가 있으면 캐시 사용)
        extract_icon_from_exe(file_path, process_id)

        # 사용자 지정 UI 배율 가져오기 (homework_helper.pyw와 동일한 로직)
        scale_factor = get_user_scale_factor()

        # 배율 적용한 물리적 픽셀 크기 계산
        # 예: 24px * 1.5 (150%) = 36px
        physical_size = int(icon_size * scale_factor)

        # 요청 크기에 맞는 아이콘 경로 가져오기 (물리적 크기 사용)
        icon_path = get_icon_for_size(process_id, physical_size)

        if icon_path and icon_path.exists():
            # 고해상도 아이콘을 QPixmap으로 로드
            pixmap = QPixmap(str(icon_path))

            if not pixmap.isNull():
                # 배율이 적용된 크기로 스케일링 (SmoothTransformation으로 고품질 유지)
                # get_icon_for_size가 이미 적절한 크기를 반환하지만, 정확한 크기 보장을 위해 스케일링
                if pixmap.width() != physical_size or pixmap.height() != physical_size:
                    scaled_pixmap = pixmap.scaled(
                        physical_size,
                        physical_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    return QIcon(scaled_pixmap)

                return QIcon(pixmap)

        # 고해상도 추출 실패 시 기존 시스템 아이콘 사용 (폴백)
        provider = QFileIconProvider()
        info = QFileInfo(file_path)
        return provider.icon(info)

    except Exception as e:
        # 오류 발생 시 기존 방식으로 폴백
        try:
            provider = QFileIconProvider()
            info = QFileInfo(file_path)
            return provider.icon(info)
        except Exception:
            return None


def is_process_running_by_path(executable_path_to_check: str) -> bool: # 이전과 동일
    try:
        normalized_path_to_check = os.path.normcase(os.path.abspath(executable_path_to_check))
        for proc in psutil.process_iter(['exe']):
            try:
                proc_exe = proc.info['exe']
                if proc_exe:
                    normalized_proc_exe = os.path.normcase(os.path.abspath(proc_exe))
                    if normalized_proc_exe == normalized_path_to_check:
                        return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, FileNotFoundError):
                continue
    except Exception as e:
        print(f"Error checking process by path: {e}")
    return False

def get_process_info_by_name(process_name_to_check: str) -> List[Dict[str, Any]]: # 이전과 동일
    found_processes = []
    # ... (이전 코드 내용 동일) ...
    try:
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'create_time']):
            try:
                if proc.info['name'] and proc.info['name'].lower() == process_name_to_check.lower():
                    process_data = {
                        'pid': proc.info['pid'], 'name': proc.info['name'],
                        'exe': proc.info['exe'] or "N/A",
                        'create_time': proc.info['create_time']
                    }
                    found_processes.append(process_data)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        print(f"Error getting process info by name: {e}")
    return found_processes


def get_all_running_processes_info() -> List[Dict[str, Any]]:
    """
    현재 실행 중인 모든 프로세스의 정보 (PID, 이름, 실행 경로, 메모리, CPU, 아이콘) 목록을 반환합니다.
    """
    processes_info = []
    for proc in psutil.process_iter(['pid', 'name', 'exe', 'memory_info', 'cpu_percent']):
        try:
            if proc.info['pid'] == 0 or not proc.info['name'] or not proc.info['exe']:
                continue
            
            mem_info = proc.info['memory_info']
            rss_memory_mb = mem_info.rss / (1024 * 1024) if mem_info else 0 
            cpu_usage = proc.info['cpu_percent'] 
            if cpu_usage is None: cpu_usage = 0.0

            exe_path = proc.info['exe']
            q_icon = get_qicon_for_file(exe_path) # 아이콘 가져오기

            process_data = {
                'pid': proc.info['pid'],
                'name': proc.info['name'],
                'exe': exe_path,
                'memory_rss_mb': rss_memory_mb,
                'cpu_percent': cpu_usage,
                'q_icon': q_icon # QIcon 객체 추가
            }
            processes_info.append(process_data)
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
            continue
        except Exception as e:
            # print(f"Error fetching full info for PID {proc.info.get('pid', 'N/A')}: {e}")
            continue 
            
    processes_info.sort(key=lambda p: p['name'].lower())
    return processes_info