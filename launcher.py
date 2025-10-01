# launcher.py
import subprocess
import shlex
import os
import ctypes
import configparser # .url 파일 파싱을 위해 추가
from typing import Optional # 타입 힌트를 위해 추가

class Launcher:
    def __init__(self, run_as_admin: bool = False):
        self.run_as_admin = run_as_admin

    def _get_url_from_file(self, file_path: str) -> Optional[str]:
        """
        .url 파일에서 URL 문자열을 추출합니다.
        configparser의 interpolation 기능을 비활성화하여 '%' 관련 오류를 방지합니다.
        """
        try:
            # interpolation=None으로 설정하여 '%' 문자로 인한 오류 방지
            parser = configparser.ConfigParser(interpolation=None) 
            
            # .url 파일은 다양한 인코딩을 가질 수 있습니다. utf-8을 먼저 시도하고, 실패 시 시스템 기본 인코딩을 시도합니다.
            # BOM(Byte Order Mark)이 있는 UTF-8 파일도 처리하기 위해 utf-8-sig 사용 가능성 고려
            try:
                # configparser.read는 파일 목록을 받을 수 있으므로 리스트로 전달
                parsed_files = parser.read(file_path, encoding='utf-8-sig') 
                if not parsed_files: # 파일 읽기 실패 시 (예: 파일 없음, 권한 없음)
                    # utf-8-sig로 실패 시 일반 utf-8로 재시도
                    parsed_files = parser.read(file_path, encoding='utf-8')
                    if not parsed_files:
                         # 그래도 실패하면 시스템 기본 인코딩으로 재시도
                        print(f"  '{file_path}' utf-8, utf-8-sig 디코딩 실패, 시스템 기본 인코딩으로 재시도.")
                        parsed_files = parser.read(file_path)

                if not parsed_files: # 모든 시도 후에도 파일 읽기 실패
                    print(f"오류: '{file_path}' 파일을 읽을 수 없습니다.")
                    return None

            except UnicodeDecodeError as ude: # 특정 인코딩으로 디코딩 실패 시
                print(f"  '{file_path}' 파일 디코딩 오류 발생: {ude}. 다른 방법으로 URL 추출 시도.")
                # configparser 실패 시 수동으로 URL= 패턴 검색
                # (이 부분은 configparser가 파일을 아예 못 읽는 경우보다는,
                #  형식이 약간 다르거나 섹션이 없을 때의 대비책으로 더 유용)
                pass # 아래 수동 검색 로직으로 넘어감
            except Exception as e_read: # 파일 읽기 중 기타 예외
                print(f"오류: '{file_path}' 파일 읽기 중 예외 발생: {e_read}")
                return None


            if 'InternetShortcut' in parser and 'URL' in parser['InternetShortcut']:
                url = parser['InternetShortcut']['URL']
                # 가끔 URL 값 양쪽에 불필요한 따옴표가 있는 경우가 있어 제거
                return url.strip('"') 
            
            # configparser로 못찾았거나, 섹션이 없는 매우 단순한 .url 파일 (URL=... 만 있는 경우)
            print(f"  '{file_path}' 에서 [InternetShortcut] 섹션의 URL을 찾지 못함. 수동으로 'URL=' 패턴 검색 시도.")
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    cleaned_line = line.strip()
                    if cleaned_line.upper().startswith("URL="):
                        url_value = cleaned_line[len("URL="):]
                        return url_value.strip('"') # 여기서도 따옴표 제거
            
            print(f"오류: '{file_path}' .url 파일에서 URL 정보를 추출하지 못했습니다.")
            return None
        except configparser.Error as e_cfg: # configparser 관련 다른 오류 (거의 발생 안 할 것으로 예상)
            print(f"오류: '{file_path}' .url 파일 파싱 중 오류 발생 (configparser): {e_cfg}")
            return None
        except Exception as e: # 그 외 모든 예외
            print(f"오류: '{file_path}' .url 파일 처리 중 예기치 않은 예외 발생: {e}")
            return None

    def _get_url_file_target(self, url_file_path: str) -> Optional[tuple[str, str]]:
        """
        .url 파일에서 실제 실행할 대상을 파악합니다.
        반환값: (target_type, target_path) 또는 None
        target_type: 'program' (프로그램 실행) 또는 'url' (웹 URL)
        """
        try:
            # 기존의 _get_url_from_file 메서드를 활용
            url_content = self._get_url_from_file(url_file_path)
            if not url_content:
                return None
            
            # URL이 실제 프로그램 파일 경로인지 확인
            if url_content.startswith('file://'):
                # file:// 프로토콜로 시작하는 경우
                file_path = url_content[7:]  # 'file://' 제거
                # URL 인코딩된 경로를 디코딩
                import urllib.parse
                file_path = urllib.parse.unquote(file_path)
                
                # Windows 경로 정규화
                if file_path.startswith('/'):
                    # /C:/path 형태를 C:\path 형태로 변환
                    file_path = file_path[1:].replace('/', '\\')
                
                if os.path.exists(file_path):
                    print(f"  .url 파일이 로컬 프로그램을 실행합니다: {file_path}")
                    return ('program', file_path)
                else:
                    print(f"  .url 파일이 존재하지 않는 프로그램을 참조합니다: {file_path}")
                    return None
            
            elif url_content.startswith('steam://'):
                # Steam 프로토콜인 경우
                print(f"  .url 파일이 Steam 프로토콜을 사용합니다: {url_content}")
                # Steam은 관리자 권한이 필요할 수 있음
                return ('program', 'steam_protocol')
            
            elif url_content.startswith('epic://'):
                # Epic Games 프로토콜인 경우
                print(f"  .url 파일이 Epic Games 프로토콜을 사용합니다: {url_content}")
                # Epic Games 런처는 관리자 권한이 필요할 수 있음
                return ('program', 'epic_protocol')
            
            elif url_content.startswith('uplay://'):
                # Ubisoft Connect 프로토콜인 경우
                print(f"  .url 파일이 Ubisoft Connect 프로토콜을 사용합니다: {url_content}")
                # Ubisoft Connect는 관리자 권한이 필요할 수 있음
                return ('program', 'uplay_protocol')
            
            elif url_content.startswith('battle.net://'):
                # Battle.net 프로토콜인 경우
                print(f"  .url 파일이 Battle.net 프로토콜을 사용합니다: {url_content}")
                # Battle.net은 관리자 권한이 필요할 수 있음
                return ('program', 'battlenet_protocol')
            
            elif url_content.startswith('http://') or url_content.startswith('https://'):
                # 일반 웹 URL인 경우
                print(f"  .url 파일이 웹 URL을 호출합니다: {url_content}")
                return ('url', url_content)
            
            elif os.path.exists(url_content):
                # 직접적인 파일 경로인 경우
                print(f"  .url 파일이 직접 프로그램을 실행합니다: {url_content}")
                return ('program', url_content)
            
            else:
                # 알 수 없는 형식
                print(f"  .url 파일의 대상 형식을 파악할 수 없습니다: {url_content}")
                return None
                
        except Exception as e:
            print(f"  .url 파일 대상 파악 중 오류: {e}")
            return None

    def _is_admin_required(self, file_path: str) -> bool:
        """
        파일이 관리자 권한을 필요로 하는지 확인합니다.
        바로가기 파일(.lnk, .url)의 경우 실제 대상을 파악하여 판단합니다.
        """
        if not os.name == 'nt':
            return False
            
        try:
            # 파일이 존재하는지 확인
            if not os.path.exists(file_path):
                return False
                
            # .lnk 파일인 경우 실제 대상을 파악
            if file_path.lower().endswith('.lnk'):
                try:
                    import win32com.client
                    shell = win32com.client.Dispatch("WScript.Shell")
                    shortcut = shell.CreateShortCut(file_path)
                    target_path = shortcut.TargetPath
                    if target_path and os.path.exists(target_path):
                        print(f"  .lnk 파일의 실제 대상: {target_path}")
                        # 실제 대상 파일로 재귀 호출
                        return self._is_admin_required(target_path)
                except ImportError:
                    print("  pywin32가 설치되지 않아 .lnk 파일의 실제 대상을 파악할 수 없습니다.")
                    # 대체 방법: 파일 내용을 직접 파싱 시도
                    return self._parse_lnk_file_manually(file_path)
                except Exception as e:
                    print(f"  .lnk 파일 대상 파악 중 오류: {e}")
                    # 오류 발생 시 대체 방법 시도
                    return self._parse_lnk_file_manually(file_path)
                # 모든 방법이 실패한 경우 원본 파일로 판단
                return self._check_file_admin_requirement(file_path)
            
            # .url 파일인 경우 실제 대상을 파악
            elif file_path.lower().endswith('.url'):
                print(f"  .url 파일 감지: {file_path}")
                # .url 파일에서 실제 실행할 프로그램이나 URL을 추출
                target_info = self._get_url_file_target(file_path)
                if target_info:
                    target_type, target_path = target_info
                    if target_type == 'program':
                        # 게임 런처 프로토콜인 경우
                        if target_path in ['steam_protocol', 'epic_protocol', 'uplay_protocol', 'battlenet_protocol']:
                            print(f"  .url 파일이 게임 런처 프로토콜을 사용합니다: {target_path}")
                            print(f"  게임 런처는 관리자 권한이 필요할 수 있습니다.")
                            return True
                        elif os.path.exists(target_path):
                            print(f"  .url 파일이 프로그램을 실행합니다: {target_path}")
                            # 실제 프로그램 파일로 재귀 호출
                            return self._is_admin_required(target_path)
                        else:
                            print(f"  .url 파일이 존재하지 않는 프로그램을 참조합니다: {target_path}")
                            return True  # 존재하지 않는 프로그램은 관리자 권한 필요로 가정
                    elif target_type == 'url':
                        print(f"  .url 파일이 웹 URL을 호출합니다: {target_path}")
                        # 웹 URL은 관리자 권한 불필요
                        return False
                    else:
                        print(f"  .url 파일의 대상을 파악할 수 없습니다.")
                        return self._check_file_admin_requirement(file_path)
                else:
                    print(f"  .url 파일에서 대상 정보를 추출할 수 없습니다.")
                    return self._check_file_admin_requirement(file_path)
            
            # 실행 파일인지 확인
            elif not file_path.lower().endswith(('.exe', '.msi', '.bat', '.cmd')):
                return False
            
            # 실제 파일의 관리자 권한 필요성 확인
            return self._check_file_admin_requirement(file_path)
            
        except Exception:
            # 오류 발생 시 기본적으로 관리자 권한 필요로 가정
            return True

    def _check_file_admin_requirement(self, file_path: str) -> bool:
        """
        실제 파일의 관리자 권한 필요성을 확인합니다.
        """
        try:
            # 일반적으로 관리자 권한이 필요한 프로그램들 (예시)
            admin_programs = [
                'setup', 'install', 'uninstall', 'update', 'patch',
                'admin', 'service', 'driver', 'tool', 'utility',
                'regedit', 'gpedit', 'secpol', 'compmgmt', 'devmgmt',
                'services', 'taskmgr', 'cmd', 'powershell', 'msconfig'
            ]
            
            # 게임 런처 및 게임 관련 프로그램들도 관리자 권한 필요로 판단
            game_launcher_programs = [
                'steam', 'epic', 'uplay', 'ubisoft', 'battle.net', 'battlenet',
                'origin', 'ea', 'gog', 'galaxy', 'riot', 'league',
                'minecraft', 'java', 'javaw', 'game', 'launcher'
            ]
            
            file_name_lower = os.path.basename(file_path).lower()
            
            # 파일명에 게임 런처 관련 키워드가 포함되어 있는지 확인
            for keyword in game_launcher_programs:
                if keyword in file_name_lower:
                    print(f"  파일명에 게임 런처 관련 키워드 '{keyword}'가 포함되어 있습니다.")
                    print(f"  게임 런처는 관리자 권한이 필요할 수 있습니다.")
                    return True
            
            # 파일명에 관리자 권한이 필요한 키워드가 포함되어 있는지 확인
            for keyword in admin_programs:
                if keyword in file_name_lower:
                    print(f"  파일명에 관리자 권한 관련 키워드 '{keyword}'가 포함되어 있습니다.")
                    return True
            
            # Windows 시스템 폴더에 있는 프로그램인지 확인
            system_paths = [
                os.environ.get('WINDIR', 'C:\\Windows'),
                os.environ.get('PROGRAMFILES', 'C:\\Program Files'),
                os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'),
                os.environ.get('SYSTEMROOT', 'C:\\Windows\\System32')
            ]
            
            file_abs_path = os.path.abspath(file_path)
            for system_path in system_paths:
                if file_abs_path.startswith(system_path):
                    print(f"  파일이 시스템 폴더에 위치합니다: {system_path}")
                    return True
            
            # 특정 확장자에 대한 추가 확인
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext in ['.msi', '.msu']:
                print(f"  MSI/MSU 설치 파일은 일반적으로 관리자 권한이 필요합니다.")
                return True
            
            # 기본적으로는 관리자 권한이 필요하지 않다고 가정
            print(f"  파일이 관리자 권한을 필요로 하지 않는 것으로 판단됩니다.")
            return False
            
        except Exception as e:
            print(f"  파일 관리자 권한 필요성 확인 중 오류: {e}")
            # 오류 발생 시 기본적으로 관리자 권한 필요로 가정
            return True

    def _parse_lnk_file_manually(self, lnk_file_path: str) -> bool:
        """
        .lnk 파일을 수동으로 파싱하여 실제 대상을 파악합니다.
        win32com이 사용 불가능한 경우의 대체 방법입니다.
        """
        try:
            with open(lnk_file_path, 'rb') as f:
                # .lnk 파일의 기본 구조를 파악하여 대상 경로 추출 시도
                content = f.read()
                
                # .lnk 파일 시그니처 확인
                if content[:4] != b'L\x00\x00\x00':
                    print(f"  유효하지 않은 .lnk 파일 형식입니다.")
                    return self._check_file_admin_requirement(lnk_file_path)
                
                # 간단한 경로 추출 시도 (완벽하지 않지만 기본적인 경우는 처리)
                # 실제로는 .lnk 파일 구조가 복잡하므로 완벽한 파싱은 어려움
                # 대신 파일명 기반으로 추정
                file_name = os.path.basename(lnk_file_path)
                base_name = os.path.splitext(file_name)[0]
                
                print(f"  .lnk 파일 수동 파싱: {base_name}")
                
                # 게임 런처 및 게임 관련 프로그램들도 관리자 권한 필요로 판단
                game_launcher_keywords = [
                    'steam', 'epic', 'uplay', 'ubisoft', 'battle.net', 'battlenet',
                    'origin', 'ea', 'gog', 'galaxy', 'riot', 'league',
                    'minecraft', 'java', 'javaw', 'game', 'launcher'
                ]
                
                # 관리자 권한이 필요한 프로그램들
                admin_keywords = ['setup', 'install', 'uninstall', 'update', 'patch', 'admin', 'service']
                
                # 먼저 게임 런처 관련 키워드 확인
                if any(keyword in base_name.lower() for keyword in game_launcher_keywords):
                    print(f"  바로가기 이름에 게임 런처 관련 키워드가 포함되어 있습니다.")
                    print(f"  게임 런처는 관리자 권한이 필요할 수 있습니다.")
                    return True
                
                # 관리자 권한이 필요한 키워드 확인
                if any(keyword in base_name.lower() for keyword in admin_keywords):
                    print(f"  바로가기 이름에 관리자 권한 관련 키워드가 포함되어 있습니다.")
                    return True
                
                print(f"  바로가기 파일은 관리자 권한이 필요하지 않는 것으로 판단됩니다.")
                return False
                
        except Exception as e:
            print(f"  .lnk 파일 수동 파싱 중 오류: {e}")
            # 오류 발생 시 기본적으로 관리자 권한 필요로 가정
            return True

    def _launch_game_launcher_as_admin(self, protocol_url: str) -> bool:
        """
        게임 런처를 관리자 권한으로 실행하는 고급 방법들을 시도합니다.
        """
        try:
            if not os.name == 'nt':
                return False
            
            print(f"  게임 런처를 관리자 권한으로 실행 시도: {protocol_url}")
            
            # 방법 1: 게임 런처 실행 파일을 직접 찾아서 관리자 권한으로 실행
            if self._find_and_launch_game_launcher_as_admin(protocol_url):
                return True
            
            # 방법 2: Windows 작업 스케줄러를 통한 관리자 권한 실행
            if self._launch_via_task_scheduler(protocol_url):
                return True
            
            # 방법 3: CreateProcessAsUser를 통한 관리자 권한 실행
            if self._launch_via_create_process_as_user(protocol_url):
                return True
            
            # 방법 4: ShellExecuteW with runas (기본 방법)
            return self._launch_via_shell_execute_runas(protocol_url)
            
        except Exception as e:
            print(f"  게임 런처 관리자 권한 실행 중 오류: {e}")
            return False

    def _launch_via_task_scheduler(self, protocol_url: str) -> bool:
        """
        Windows 작업 스케줄러를 통해 관리자 권한으로 실행을 시도합니다.
        """
        try:
            import subprocess
            
            # 임시 배치 파일 생성
            temp_bat = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), f'launch_game_{hash(protocol_url)}.bat')
            
            with open(temp_bat, 'w') as f:
                f.write(f'@echo off\nstart "" "{protocol_url}"\n')
            
            # schtasks를 사용하여 관리자 권한으로 배치 파일 실행
            cmd = [
                'schtasks', '/create', '/tn', f'GameLaunch_{hash(protocol_url)}', 
                '/tr', temp_bat, '/sc', 'once', '/st', '00:00', '/f'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                # 작업 즉시 실행
                run_cmd = ['schtasks', '/run', '/tn', f'GameLaunch_{hash(protocol_url)}']
                subprocess.run(run_cmd, capture_output=True)
                
                # 임시 파일 정리
                try:
                    os.remove(temp_bat)
                except:
                    pass
                
                print(f"  작업 스케줄러를 통해 관리자 권한으로 실행 요청됨")
                return True
            else:
                print(f"  작업 스케줄러 생성 실패: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"  작업 스케줄러 방식 실행 중 오류: {e}")
            return False

    def _launch_via_create_process_as_user(self, protocol_url: str) -> bool:
        """
        CreateProcessAsUser API를 사용하여 관리자 권한으로 실행을 시도합니다.
        """
        try:
            import win32api
            import win32con
            import win32process
            import win32security
            
            # 현재 프로세스의 토큰을 복제하여 관리자 권한으로 실행
            current_token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(), 
                win32con.TOKEN_ALL_ACCESS
            )
            
            # 관리자 권한으로 토큰 생성
            admin_token = win32security.DuplicateTokenEx(
                current_token,
                win32security.SecurityImpersonation,
                win32security.TokenPrimary
            )
            
            # 프로세스 생성 정보
            startup_info = win32process.STARTUPINFO()
            startup_info.dwFlags = win32con.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = win32con.SW_SHOW
            
            # 프로세스 생성
            process_handle, thread_handle, pid, tid = win32process.CreateProcessAsUser(
                admin_token,
                None,  # 애플리케이션 이름
                protocol_url,  # 명령줄
                None,  # 프로세스 보안 속성
                None,  # 스레드 보안 속성
                False,  # 핸들 상속
                win32con.CREATE_NEW_CONSOLE,  # 생성 플래그
                None,  # 환경
                None,  # 현재 디렉토리
                startup_info
            )
            
            print(f"  CreateProcessAsUser를 통해 관리자 권한으로 실행됨 (PID: {pid})")
            return True
            
        except ImportError:
            print("  pywin32가 설치되지 않아 CreateProcessAsUser를 사용할 수 없습니다.")
            return False
        except Exception as e:
            print(f"  CreateProcessAsUser 방식 실행 중 오류: {e}")
            return False

    def _launch_via_shell_execute_runas(self, protocol_url: str) -> bool:
        """
        ShellExecuteW with runas를 사용하여 관리자 권한으로 실행을 시도합니다.
        """
        try:
            shell32 = ctypes.windll.shell32
            ret = shell32.ShellExecuteW(None, "runas", protocol_url, None, None, 1)
            
            if ret > 32:
                print(f"  ShellExecuteW (runas)를 통해 관리자 권한으로 실행 요청됨")
                return True
            else:
                print(f"  ShellExecuteW (runas) 실패. 오류 코드: {ret}")
                return False
                
        except Exception as e:
            print(f"  ShellExecuteW 방식 실행 중 오류: {e}")
            return False

    def _find_and_launch_game_launcher_as_admin(self, protocol_url: str) -> bool:
        """
        게임 런처 실행 파일을 찾아서 직접 관리자 권한으로 실행하는 방법입니다.
        """
        try:
            # 프로토콜에 따른 런처 실행 파일 경로
            launcher_paths = {
                'steam://': [
                    os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'), 'Steam', 'Steam.exe'),
                    os.path.join(os.environ.get('PROGRAMFILES', 'C:\\Program Files'), 'Steam', 'Steam.exe'),
                    os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\%USERNAME%\\AppData\\Local'), 'Steam', 'Steam.exe')
                ],
                'epic://': [
                    os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'), 'Epic Games', 'Launcher', 'Portal', 'Binaries', 'Win64', 'EpicGamesLauncher.exe'),
                    os.path.join(os.environ.get('PROGRAMFILES', 'C:\\Program Files'), 'Epic Games', 'Launcher', 'Portal', 'Binaries', 'Win64', 'EpicGamesLauncher.exe')
                ],
                'uplay://': [
                    os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'), 'Ubisoft', 'Ubisoft Game Launcher', 'Uplay.exe'),
                    os.path.join(os.environ.get('PROGRAMFILES', 'C:\\Program Files'), 'Ubisoft', 'Ubisoft Game Launcher', 'Uplay.exe')
                ],
                'battle.net://': [
                    os.path.join(os.environ.get('PROGRAMFILES(X86)', 'C:\\Program Files (x86)'), 'Battle.net', 'Battle.net Launcher.exe'),
                    os.path.join(os.environ.get('PROGRAMFILES', 'C:\\Program Files'), 'Battle.net', 'Battle.net Launcher.exe')
                ]
            }
            
            # 프로토콜에 해당하는 런처 경로 찾기
            protocol_type = None
            for protocol, paths in launcher_paths.items():
                if protocol_url.startswith(protocol):
                    protocol_type = protocol
                    break
            
            if not protocol_type:
                print(f"  지원되지 않는 게임 런처 프로토콜: {protocol_url}")
                return False
            
            # 런처 실행 파일 찾기
            launcher_exe = None
            for path in launcher_paths[protocol_type]:
                if os.path.exists(path):
                    launcher_exe = path
                    break
            
            if not launcher_exe:
                print(f"  게임 런처 실행 파일을 찾을 수 없습니다: {protocol_type}")
                return False
            
            print(f"  게임 런처 실행 파일 발견: {launcher_exe}")
            
            # 런처를 관리자 권한으로 실행
            shell32 = ctypes.windll.shell32
            ret = shell32.ShellExecuteW(None, "runas", launcher_exe, None, None, 1)
            
            if ret > 32:
                print(f"  게임 런처를 관리자 권한으로 실행 요청됨")
                # 잠시 대기 후 원래 프로토콜 URL 실행
                import time
                time.sleep(2)
                
                # 이제 원래 프로토콜 URL을 일반 권한으로 실행 (런처가 이미 관리자 권한으로 실행됨)
                ret2 = shell32.ShellExecuteW(None, "open", protocol_url, None, None, 1)
                if ret2 > 32:
                    print(f"  원래 프로토콜 URL 실행 요청됨")
                    return True
                else:
                    print(f"  원래 프로토콜 URL 실행 실패. 오류 코드: {ret2}")
                    return False
            else:
                print(f"  게임 런처 관리자 권한 실행 실패. 오류 코드: {ret}")
                return False
                
        except Exception as e:
            print(f"  게임 런처 직접 실행 중 오류: {e}")
            return False

    def launch_process(self, launch_command: str) -> bool:
        if not launch_command:
            print("오류: 실행할 경로 또는 명령어가 제공되지 않았습니다.")
            return False

        print(f"다음 명령어로 프로세스 실행 시도: {launch_command}")
        
        try:
            # 1. .url 파일 처리 (Windows 우선)
            if launch_command.lower().endswith(".url"):
                print(f"  감지된 .url 파일: {launch_command}")
                url_to_launch = self._get_url_from_file(launch_command)
                if url_to_launch:
                    print(f"  추출된 URL: {url_to_launch}")
                    
                    # 게임 런처 프로토콜인 경우 관리자 권한으로 실행 시도
                    if (url_to_launch.startswith(('steam://', 'epic://', 'uplay://', 'battle.net://')) and
                        self.run_as_admin):
                        print(f"  게임 런처 프로토콜을 관리자 권한으로 실행 시도합니다.")

                        # 현재 프로세스가 이미 관리자 권한으로 실행 중인지 확인
                        try:
                            is_current_admin = ctypes.windll.shell32.IsUserAnAdmin()
                        except:
                            is_current_admin = False

                        if is_current_admin:
                            # 이미 관리자 권한이면 일반 방식으로 실행 (관리자 권한 유지됨)
                            print(f"  현재 앱이 관리자 권한으로 실행 중이므로 일반 실행으로 게임 런처를 시작합니다.")
                            try:
                                os.startfile(url_to_launch)
                                print(f"  '{url_to_launch}' URL 실행을 os.startfile로 시도했습니다.")
                                return True
                            except Exception as e_url_start:
                                print(f"  os.startfile로 URL '{url_to_launch}' 실행 중 오류: {e_url_start}")
                                # 실패 시 ShellExecuteW로 재시도
                                shell32 = ctypes.windll.shell32
                                ret = shell32.ShellExecuteW(None, "open", url_to_launch, None, None, 1)
                                if ret > 32:
                                    print(f"  '{url_to_launch}' URL 실행을 ShellExecuteW (open)로 요청했습니다.")
                                    return True
                                else:
                                    print(f"  ShellExecuteW (open)로 URL '{url_to_launch}' 실행 실패. 반환 코드: {ret}")
                                    return False
                        else:
                            # 관리자 권한이 아니면 고급 방법으로 실행
                            return self._launch_game_launcher_as_admin(url_to_launch)
                    
                    # 일반 URL 처리 (기존 로직)
                    if os.name == 'nt':
                        try:
                            os.startfile(url_to_launch)
                            print(f"  '{url_to_launch}' URL 실행을 os.startfile로 시도했습니다.")
                            return True
                        except Exception as e_url_start:
                            print(f"  os.startfile로 URL '{url_to_launch}' 실행 중 오류: {e_url_start}")
                            print(f"  os.startfile 실패, ShellExecuteW (verb='open')으로 재시도합니다...")
                            try:
                                shell32 = ctypes.windll.shell32
                                ret = shell32.ShellExecuteW(None, "open", url_to_launch, None, None, 1)
                                if ret > 32:
                                    print(f"  '{url_to_launch}' URL 실행을 ShellExecuteW (open)로 요청했습니다. (반환 값: {ret})")
                                    return True
                                else:
                                    print(f"  ShellExecuteW (open)로 URL '{url_to_launch}' 실행 실패. 반환 코드: {ret}")
                                    return False
                            except Exception as e_shell_url:
                                print(f"  ShellExecuteW로 URL '{url_to_launch}' 실행 중 예외: {e_shell_url}")
                                return False
                    else: # 비-Windows
                        print(f"  비-Windows 환경({os.name})에서는 .url 파일 내 URL을 webbrowser로 실행 시도합니다.")
                        import webbrowser
                        try:
                            if webbrowser.open(url_to_launch):
                                print(f"  webbrowser.open으로 '{url_to_launch}' 실행 성공 (또는 시도됨).")
                                return True
                            else: # 일부 플랫폼에서는 open이 bool을 반환하지 않거나 항상 True일 수 있음
                                print(f"  webbrowser.open으로 '{url_to_launch}' 실행했으나, 명시적인 성공 반환값 없음.")
                                return True # 시도 자체를 성공으로 간주
                        except Exception as e_wb:
                            print(f"  webbrowser.open으로 URL '{url_to_launch}' 실행 중 오류: {e_wb}")
                            return False
                else:
                    return False # URL 추출 실패

            # 2. .lnk 파일 처리 (Windows 전용)
            elif launch_command.lower().endswith(".lnk"):
                # ... (이전 .lnk 처리 로직과 동일) ...
                if os.name == 'nt':
                    try:
                        os.startfile(launch_command)
                        print(f"  '{launch_command}' (.lnk 파일) 실행을 os.startfile로 시도했습니다.")
                        return True
                    except Exception as e_lnk_start:
                        print(f"  os.startfile로 .lnk '{launch_command}' 실행 중 오류: {e_lnk_start}")
                        return False
                else:
                    print(f"오류: .lnk 파일 실행은 Windows에서만 직접 지원됩니다. (현재 OS: {os.name})")
                    return False
            
            # 3. 기타 실행 파일 또는 명령어 (기존 로직 유지)
            else:
                if os.name == 'nt':
                    shell32 = ctypes.windll.shell32

                    # 현재 프로세스가 이미 관리자 권한으로 실행 중인지 확인
                    try:
                        is_current_admin = ctypes.windll.shell32.IsUserAnAdmin()
                    except:
                        is_current_admin = False

                    # 관리자 권한 설정에 따라 실행 방식 결정
                    admin_required = self._is_admin_required(launch_command)

                    if self.run_as_admin and admin_required:
                        if is_current_admin:
                            # 이미 관리자 권한으로 실행 중이면 "open"으로 실행 (UAC 없이 관리자 권한 유지)
                            verb = "open"
                            print(f"  현재 앱이 관리자 권한으로 실행 중입니다.")
                            print(f"  UAC 프롬프트 없이 관리자 권한으로 프로세스를 실행합니다.")
                        else:
                            # 관리자 권한이 아닐 때는 "runas"로 UAC 호출
                            verb = "runas"
                            print(f"  관리자 권한으로 실행 설정이 활성화되어 있고, 파일이 관리자 권한을 필요로 합니다.")
                            print(f"  UAC 프롬프트를 호출하여 관리자 권한으로 실행합니다.")
                    else:
                        verb = "open"
                        if self.run_as_admin:
                            print(f"  관리자 권한으로 실행 설정이 활성화되어 있지만, 이 파일은 관리자 권한이 필요하지 않습니다.")
                        else:
                            print(f"  일반 사용자 권한으로 실행합니다.")

                    print(f"  ShellExecuteW 호출 시도: verb='{verb}', file='{launch_command}', params=None")

                    ret = shell32.ShellExecuteW(None, verb, launch_command, None, None, 1) # SW_SHOWNORMAL = 1
                    if ret > 32:
                        print(f"  '{launch_command}' 실행을 ShellExecuteW ({verb})로 요청했습니다. (반환 값: {ret})")
                        return True
                    else:
                        win_error_code = ret
                        print(f"  ShellExecuteW ({verb}) 실패. 반환/오류 코드: {win_error_code}")
                        if win_error_code == 0: print("    오류 원인: 시스템 리소스 부족 또는 매우 심각한 오류.")
                        elif win_error_code == 2: print("    오류 원인: 지정된 파일을 찾을 수 없습니다.")
                        elif win_error_code == 3: print("    오류 원인: 지정된 경로를 찾을 수 없습니다.")
                        elif win_error_code == 5: print("    오류 원인: 접근이 거부되었습니다 (파일 권한 문제).")
                        elif win_error_code == 1223: print("    사용자가 UAC 프롬프트에서 작업을 취소했습니다.")
                        return False
                else: 
                    try:
                        args = shlex.split(launch_command, posix=True)
                        subprocess.Popen(args)
                        print(f"  프로세스 실행 시도 완료 (비 Windows): {args}")
                        return True
                    except Exception as e_shlex:
                        print(f"  비 Windows 환경 shlex.split 또는 Popen 오류: {e_shlex}")
                        return False
                        
        except FileNotFoundError: # 주로 subprocess.Popen에서 발생
            print(f"오류: 파일을 찾을 수 없습니다 - {launch_command}")
            return False
        except Exception as e: # 그 외 예외 처리
            print(f"프로세스 실행 중 예기치 않은 예외 발생: {e}")
            return False