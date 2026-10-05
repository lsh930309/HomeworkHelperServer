"""Headless Windows launch policy and shortcut reads shared by app and service.

These functions observe registered targets without importing GUI, API, database
writers or a process launcher. Target and argument selection remains pure in
launch_target.py.
"""
import configparser
import os
from typing import Optional

def read_url_target(file_path: str) -> Optional[str]:
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


def url_file_target(url_file_path: str) -> Optional[tuple[str, str]]:
    """
    .url 파일에서 실제 실행할 대상을 파악합니다.
    반환값: (target_type, target_path) 또는 None
    target_type: 'program' (프로그램 실행) 또는 'url' (웹 URL)
    """
    try:
        # 기존의 _get_url_from_file 메서드를 활용
        url_content = read_url_target(url_file_path)
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


def launch_admin_required(file_path: str) -> bool:
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
                    return launch_admin_required(target_path)
            except ImportError:
                print("  pywin32가 설치되지 않아 .lnk 파일의 실제 대상을 파악할 수 없습니다.")
                # 대체 방법: 파일 내용을 직접 파싱 시도
                return parse_lnk_admin_requirement(file_path)
            except Exception as e:
                print(f"  .lnk 파일 대상 파악 중 오류: {e}")
                # 오류 발생 시 대체 방법 시도
                return parse_lnk_admin_requirement(file_path)
            # 모든 방법이 실패한 경우 원본 파일로 판단
            return file_admin_required(file_path)

        # .url 파일인 경우 실제 대상을 파악
        elif file_path.lower().endswith('.url'):
            print(f"  .url 파일 감지: {file_path}")
            # .url 파일에서 실제 실행할 프로그램이나 URL을 추출
            target_info = url_file_target(file_path)
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
                        return launch_admin_required(target_path)
                    else:
                        print(f"  .url 파일이 존재하지 않는 프로그램을 참조합니다: {target_path}")
                        return True  # 존재하지 않는 프로그램은 관리자 권한 필요로 가정
                elif target_type == 'url':
                    print(f"  .url 파일이 웹 URL을 호출합니다: {target_path}")
                    # 웹 URL은 관리자 권한 불필요
                    return False
                else:
                    print(f"  .url 파일의 대상을 파악할 수 없습니다.")
                    return file_admin_required(file_path)
            else:
                print(f"  .url 파일에서 대상 정보를 추출할 수 없습니다.")
                return file_admin_required(file_path)

        # 실행 파일인지 확인
        elif not file_path.lower().endswith(('.exe', '.msi', '.bat', '.cmd')):
            return False

        # 실제 파일의 관리자 권한 필요성 확인
        return file_admin_required(file_path)

    except Exception:
        # 오류 발생 시 기본적으로 관리자 권한 필요로 가정
        return True


def file_admin_required(file_path: str) -> bool:
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


def parse_lnk_admin_requirement(lnk_file_path: str) -> bool:
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
                return file_admin_required(lnk_file_path)

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

