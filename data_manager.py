# data_manager.py
import json
import os
from typing import List, Optional, Dict
from data_models import ManagedProcess, GlobalSettings, WebShortcut # 바로 위 파일에서 정의한 클래스 임포트
from utils import copy_shortcut_file, get_shortcuts_directory, get_base_path # 바로가기 복사 기능 및 경로 함수

class DataManager:
    """
    ManagedProcess 객체들과 GlobalSettings 객체를 JSON 파일에서 로드하고 저장합니다.
    """
    def __init__(self, data_folder: str = "homework_helper_data"):
        # 실행 파일 기준 homework_helper_data 경로 계산
        base_path = get_base_path()
        self.data_folder = os.path.join(base_path, data_folder)
        
        if not os.path.exists(self.data_folder):
            os.makedirs(self.data_folder) # 데이터 저장 폴더 생성
        
        # shortcuts 디렉토리도 함께 생성
        shortcuts_dir = os.path.join(self.data_folder, "shortcuts")
        if not os.path.exists(shortcuts_dir):
            os.makedirs(shortcuts_dir)

        self.settings_file_path = os.path.join(self.data_folder, "global_settings.json")
        self.processes_file_path = os.path.join(self.data_folder, "managed_processes.json")
        self.web_shortcuts_file_path = os.path.join(self.data_folder, "web_shortcuts.json")
        
        self.global_settings: GlobalSettings = self._load_global_settings()
        self.managed_processes: List[ManagedProcess] = self._load_managed_processes()
        self.web_shortcuts: List[WebShortcut] = self._load_web_shortcuts()
        
        # 기존 데이터 모델 마이그레이션 및 바로가기 파일 복사
        self._migrate_existing_data()
        self._ensure_existing_shortcuts()

    def _load_global_settings(self) -> GlobalSettings:
        """파일에서 전역 설정을 로드합니다. 파일이 없으면 기본값으로 객체를 생성합니다."""
        if os.path.exists(self.settings_file_path):
            try:
                with open(self.settings_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return GlobalSettings.from_dict(data)
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Error loading global settings: {e}. Using default settings.")
                return GlobalSettings() # 오류 발생 시 기본 설정 사용
        return GlobalSettings() # 파일 없을 시 기본 설정 사용

    def save_global_settings(self):
        """파일에 현재 전역 설정을 저장합니다."""
        try:
            with open(self.settings_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.global_settings.to_dict(), f, ensure_ascii=False, indent=4)
        except IOError as e:
            print(f"Error saving global settings: {e}")

    def _load_managed_processes(self) -> List[ManagedProcess]:
        """파일에서 관리 대상 프로세스 목록을 로드합니다."""
        if os.path.exists(self.processes_file_path):
            try:
                with open(self.processes_file_path, 'r', encoding='utf-8') as f:
                    data_list = json.load(f)
                    return [ManagedProcess.from_dict(data) for data in data_list]
            except (json.JSONDecodeError, TypeError) as e:
                print(f"Error loading managed processes: {e}. Returning empty list.")
                return [] # 오류 발생 시 빈 목록 반환
        return [] # 파일 없을 시 빈 목록 반환

    def save_managed_processes(self):
        """파일에 현재 관리 대상 프로세스 목록을 저장합니다."""
        try:
            data_list = [process.to_dict() for process in self.managed_processes]
            with open(self.processes_file_path, 'w', encoding='utf-8') as f:
                json.dump(data_list, f, ensure_ascii=False, indent=4)
        except IOError as e:
            print(f"Error saving managed processes: {e}")

    def add_process(self, process: ManagedProcess) -> bool:
        """새로운 프로세스를 목록에 추가하고 저장합니다."""
        if any(p.id == process.id for p in self.managed_processes):
            print(f"Process with ID {process.id} already exists.")
            return False
        self.managed_processes.append(process)
        self.save_managed_processes()
        return True

    def remove_process(self, process_id: str) -> bool:
        """ID로 프로세스를 찾아 목록에서 제거하고 저장합니다."""
        initial_len = len(self.managed_processes)
        self.managed_processes = [p for p in self.managed_processes if p.id != process_id]
        if len(self.managed_processes) < initial_len:
            self.save_managed_processes()
            return True
        print(f"Process with ID {process_id} not found.")
        return False

    def update_process(self, updated_process: ManagedProcess) -> bool:
        """기존 프로세스 정보를 업데이트하고 저장합니다."""
        for i, p in enumerate(self.managed_processes):
            if p.id == updated_process.id:
                self.managed_processes[i] = updated_process
                self.save_managed_processes()
                return True
        print(f"Process with ID {updated_process.id} not found for update.")
        return False

    def get_process_by_id(self, process_id: str) -> Optional[ManagedProcess]:
        """ID로 프로세스를 찾아 반환합니다."""
        for process in self.managed_processes:
            if process.id == process_id:
                return process
        return None
    
    def _load_web_shortcuts(self) -> List[WebShortcut]:
        """ 저장된 웹 바로 가기 목록을 불러옵니다. 파일이 없거나 비어있으면 기본값을 생성합니다. """
        shortcuts = []
        file_exists = os.path.exists(self.web_shortcuts_file_path)
        
        if file_exists:
            try:
                with open(self.web_shortcuts_file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    loaded_data = data.get("web_shortcuts")
                    if isinstance(loaded_data, list):
                        shortcuts = [WebShortcut.from_dict(item) for item in loaded_data]
                    else:
                        print(f"경고: '{self.web_shortcuts_file_path}' 파일 형식이 잘못되었거나 'web_shortcuts' 리스트가 없습니다. 기본값으로 대체합니다.")
                        file_exists = False 
            except (IOError, json.JSONDecodeError, TypeError) as e:
                print(f"웹 바로 가기 파일 로드 오류: {e}. 기본값으로 대체합니다.")
                file_exists = False
        
        if not file_exists or not shortcuts: # 파일이 없거나, 있었지만 비어있거나, 로드에 실패한 경우
            print("웹 바로 가기 데이터가 없거나 로드에 실패하여 기본값을 생성합니다.")
            default_shortcuts = [
                WebShortcut(
                    name="스타레일 출석",
                    url="https://act.hoyolab.com/bbs/event/signin/hkrpg/e202303301540311.html?act_id=e202303301540311&bbs_auth_required=true&bbs_presentation_style=fullscreen&lang=ko-kr&utm_source=share&utm_medium=link&utm_campaign=web",
                    refresh_time_str="05:00" # 예시: 매일 새벽 5시 초기화
                ),
                WebShortcut(
                    name="젠존제 출석",
                    url="https://act.hoyolab.com/bbs/event/signin/zzz/e202406031448091.html?act_id=e202406031448091&bbs_auth_required=true&bbs_presentation_style=fullscreen&lang=ko-kr&utm_source=share&utm_medium=link&utm_campaign=web",
                    refresh_time_str="05:00" # 예시: 매일 새벽 5시 초기화
                )
            ]
            # last_reset_timestamp는 초기에 None으로 설정됨 (WebShortcut 생성자 기본값)
            shortcuts = default_shortcuts
            self._save_web_shortcuts(shortcuts) 
            
        return shortcuts

    def _save_web_shortcuts(self, shortcuts: List[WebShortcut]):
        """ 웹 바로 가기 목록을 파일에 저장합니다. """
        try:
            with open(self.web_shortcuts_file_path, 'w', encoding='utf-8') as f:
                # WebShortcut 객체를 딕셔너리로 변환하여 저장
                json.dump({"web_shortcuts": [sc.to_dict() for sc in shortcuts]}, f, indent=4, ensure_ascii=False)
        except IOError as e:
            print(f"웹 바로 가기 파일 저장 오류: {e}")

    def get_web_shortcuts(self) -> List[WebShortcut]:
        """ 모든 웹 바로 가기 목록을 반환합니다. """
        return list(self.web_shortcuts) # 복사본 반환

    def add_web_shortcut(self, shortcut: WebShortcut) -> bool:
        """ 새 웹 바로 가기를 추가합니다. """
        if not isinstance(shortcut, WebShortcut):
            return False
        # 이름 중복 방지 (선택 사항)
        # if any(sc.name == shortcut.name for sc in self.web_shortcuts):
        #     print(f"오류: 웹 바로 가기 이름 '{shortcut.name}'이(가) 이미 존재합니다.")
        #     return False
        self.web_shortcuts.append(shortcut)
        self._save_web_shortcuts(self.web_shortcuts)
        print(f"웹 바로 가기 추가됨: {shortcut.name}")
        return True

    def get_web_shortcut_by_id(self, shortcut_id: str) -> Optional[WebShortcut]:
        """ ID로 웹 바로 가기를 찾습니다. """
        for shortcut in self.web_shortcuts:
            if shortcut.id == shortcut_id:
                return shortcut
        return None

    def update_web_shortcut(self, updated_shortcut: WebShortcut) -> bool:
        """ 기존 웹 바로 가기 정보를 업데이트합니다. """
        for i, shortcut in enumerate(self.web_shortcuts):
            if shortcut.id == updated_shortcut.id:
                self.web_shortcuts[i] = updated_shortcut
                self._save_web_shortcuts(self.web_shortcuts)
                print(f"웹 바로 가기 업데이트됨: {updated_shortcut.name}")
                return True
        print(f"오류: 업데이트할 웹 바로 가기 ID '{updated_shortcut.id}'을(를) 찾을 수 없습니다.")
        return False

    def remove_web_shortcut(self, shortcut_id: str) -> bool:
        """ ID로 웹 바로 가기를 삭제합니다. """
        original_len = len(self.web_shortcuts)
        self.web_shortcuts = [sc for sc in self.web_shortcuts if sc.id != shortcut_id]
        if len(self.web_shortcuts) < original_len:
            self._save_web_shortcuts(self.web_shortcuts)
            print(f"웹 바로 가기 ID '{shortcut_id}' 삭제됨.")
            return True
        print(f"오류: 삭제할 웹 바로 가기 ID '{shortcut_id}'을(를) 찾을 수 없습니다.")
        return False

    def _migrate_existing_data(self):
        """기존 데이터를 새로운 모델 형식으로 마이그레이션합니다."""
        print("\n=== 기존 데이터 모델 마이그레이션 시작 ===")
        
        has_changes = False
        for i, process in enumerate(self.managed_processes):
            print(f"\n--- 프로세스 {i+1}: {process.name} ---")
            
            # original_launch_path 필드가 없으면 추가
            if not hasattr(process, 'original_launch_path') or process.original_launch_path is None:
                process.original_launch_path = process.launch_path
                has_changes = True
                print(f"✅ original_launch_path 필드 추가: {process.original_launch_path}")
            else:
                print(f"original_launch_path 필드 이미 존재: {process.original_launch_path}")
        
        if has_changes:
            print("\n마이그레이션 완료 - 변경사항을 저장합니다.")
            self.save_managed_processes()
        else:
            print("\n마이그레이션 불필요 - 모든 데이터가 최신 형식입니다.")
        
        print("=== 기존 데이터 모델 마이그레이션 완료 ===\n")

    def _ensure_existing_shortcuts(self):
        """기존 프로그램들의 바로가기 파일이 shortcuts 폴더에 있는지 확인하고, 없으면 복사합니다."""
        print("=== 기존 바로가기 파일 확인 시작 ===")
        shortcuts_dir = get_shortcuts_directory()
        print(f"shortcuts 디렉토리 경로: {shortcuts_dir}")
        
        # shortcuts 디렉토리가 없으면 생성
        if not os.path.exists(shortcuts_dir):
            os.makedirs(shortcuts_dir, exist_ok=True)
            print(f"shortcuts 디렉토리 생성됨: {shortcuts_dir}")
        
        # shortcuts 폴더에 있는 파일 목록
        existing_shortcuts = set()
        try:
            for filename in os.listdir(shortcuts_dir):
                existing_shortcuts.add(filename.lower())
            print(f"기존 shortcuts 파일들: {list(existing_shortcuts)}")
        except Exception as e:
            print(f"shortcuts 디렉토리 읽기 실패: {e}")
            return
        
        print(f"등록된 프로세스 수: {len(self.managed_processes)}")
        
        # 각 프로세스의 실행 경로 확인
        has_changes = False
        for i, process in enumerate(self.managed_processes):
            print(f"\n--- 프로세스 {i+1}: {process.name} ---")
            launch_path = process.launch_path
            original_path = getattr(process, 'original_launch_path', launch_path)
            print(f"현재 실행 경로: {launch_path}")
            print(f"원본 실행 경로: {original_path}")
            
            if not launch_path:
                print("실행 경로가 비어있음")
                continue
            
            # 원본 경로가 존재하지 않으면 경고
            if original_path and not os.path.exists(original_path):
                print(f"⚠️ 원본 파일이 존재하지 않음: {original_path}")
                # 원본 경로 정보는 유지하되, 현재 실행 경로가 유효한지 확인
                if not os.path.exists(launch_path):
                    print(f"❌ 현재 실행 경로도 존재하지 않음: {launch_path}")
                    print(f"프로세스 '{process.name}'의 실행 경로가 유효하지 않습니다.")
                    continue
            
            # 바로가기 파일인지 확인 (원본 경로 기준)
            file_ext = os.path.splitext(original_path)[1].lower()
            print(f"원본 파일 확장자: {file_ext}")
            
            if file_ext not in ['.lnk', '.url']:
                print("바로가기 파일이 아님 (건너뜀)")
                continue
            
            # 이미 shortcuts 폴더에 있는지 확인 (현재 경로 기준)
            current_filename = os.path.basename(launch_path)
            original_filename = os.path.basename(original_path)
            print(f"현재 파일명: {current_filename}")
            print(f"원본 파일명: {original_filename}")
            
            # 현재 경로가 이미 shortcuts 폴더에 있으면 건너뜀
            if current_filename.lower() in existing_shortcuts:
                print(f"바로가기 파일이 이미 shortcuts 폴더에 존재합니다: {current_filename}")
                continue
            
            # 원본 파일을 shortcuts 폴더에 복사
            print(f"원본 바로가기 파일을 복사합니다: {original_filename}")
            copied_path = copy_shortcut_file(original_path)
            if copied_path:
                # 프로세스의 실행 경로를 복사된 경로로 업데이트 (원본 경로는 보존)
                process.launch_path = copied_path
                if not hasattr(process, 'original_launch_path'):
                    process.original_launch_path = original_path
                has_changes = True
                print(f"✅ 프로세스 실행 경로 업데이트: {process.name} -> {copied_path}")
            else:
                print(f"❌ 바로가기 파일 복사 실패: {original_path}")
        
        # 변경사항이 있으면 저장
        if has_changes:
            self.save_managed_processes()
            print("기존 프로그램들의 바로가기 파일 복사 및 경로 업데이트 완료")
        else:
            print("변경사항 없음")
        
        print("=== 기존 바로가기 파일 확인 완료 ===")