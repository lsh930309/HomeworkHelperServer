# process_utils.py
import psutil
from typing import List, Dict, Any, Optional
import os
from PyQt6.QtWidgets import QFileIconProvider # 아이콘 제공자
from PyQt6.QtCore import QFileInfo          # 파일 정보 객체

# QFileIconProvider는 애플리케이션 컨텍스트에서 생성되는 것이 좋을 수 있으나,
# 여기서 간단히 사용하기 위해 전역 또는 함수 내 지역 변수로 생성합니다.
# 앱 전체에서 하나의 인스턴스를 공유하는 것이 더 효율적일 수 있습니다.
# 여기서는 함수 호출 시마다 생성 (간단한 접근)
# icon_provider = QFileIconProvider() # 전역으로 두거나, GUI 클래스 멤버로 전달 가능

def get_qicon_for_file(file_path: Optional[str]) -> Optional[Any]: # 반환 타입을 Any로 (QIcon)
    """ 주어진 파일 경로에 대한 QIcon 객체를 반환합니다. 실패 시 None. """
    if not file_path or not os.path.exists(file_path): # 파일이 존재해야 아이콘을 가져올 수 있음
        return None
    try:
        # QFileIconProvider는 QApplication이 실행 중일 때 제대로 동작하는 경우가 많습니다.
        # 이 함수가 GUI 스레드에서 호출된다고 가정합니다.
        provider = QFileIconProvider()
        info = QFileInfo(file_path)
        return provider.icon(info)
    except Exception as e:
        # print(f"Error getting QIcon for {file_path}: {e}") # 디버깅 시 사용
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