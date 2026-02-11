# dashboard/icons.py
"""게임 아이콘 추출 및 캐시 관리"""

import os
import hashlib
from pathlib import Path

# 아이콘 캐시 디렉토리
ICON_CACHE_DIR = os.path.join(
    os.getenv('APPDATA', os.path.expanduser('~')), 
    'HomeworkHelper', 
    'icon_cache'
)

# 기본 색상 팔레트 (HSL 기반으로 더 구분 가능하게)
GAME_COLORS = [
    '#6366f1',  # 인디고
    '#22c55e',  # 그린
    '#f59e0b',  # 앰버
    '#ef4444',  # 레드
    '#8b5cf6',  # 바이올렛
    '#ec4899',  # 핑크
    '#06b6d4',  # 시안
    '#84cc16',  # 라임
    '#f97316',  # 오렌지
    '#14b8a6',  # 틸
    '#a855f7',  # 퍼플
    '#3b82f6',  # 블루
    '#eab308',  # 옐로우
    '#64748b',  # 슬레이트
    '#0ea5e9',  # 스카이
]


def get_color_for_game(name: str, index: int = None) -> str:
    """게임 이름 기반 고유 색상 반환 (인덱스 우선)"""
    if index is not None:
        return GAME_COLORS[index % len(GAME_COLORS)]
    
    # 이름 해시 기반 색상 선택
    hash_val = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    return GAME_COLORS[hash_val % len(GAME_COLORS)]


def ensure_cache_dir():
    """캐시 디렉토리 생성"""
    os.makedirs(ICON_CACHE_DIR, exist_ok=True)


def get_cached_icon_path(process_id: str) -> Path:
    """캐시된 아이콘 경로 반환 (버전 포함)"""
    # 아이콘 추출 방식 변경 시 버전 업데이트하여 캐시 무효화
    version = "v4_native"
    return Path(ICON_CACHE_DIR) / f"{process_id}_{version}.png"


def resolve_shortcut(lnk_path: str) -> str | None:
    """바로가기(.lnk) 파일에서 대상 경로 추출"""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(lnk_path)
        return shortcut.TargetPath
    except Exception:
        return None


def extract_icon_from_exe(exe_path: str, process_id: str) -> str | None:
    """
    실행 파일에서 고해상도 아이콘 추출

    Returns:
        캐시된 아이콘 파일 경로 또는 None
    """
    try:
        ensure_cache_dir()
        cache_path = get_cached_icon_path(process_id)

        # 이미 캐시된 경우
        if cache_path.exists():
            return str(cache_path)

        # 바로가기 파일인 경우 대상 경로 추출
        actual_path = exe_path
        if exe_path.lower().endswith('.lnk'):
            resolved = resolve_shortcut(exe_path)
            if resolved and os.path.exists(resolved):
                actual_path = resolved
            else:
                return None

        # 실행 파일 존재 확인
        if not os.path.exists(actual_path):
            return None

        from PIL import Image
        import struct

        # 방법 1: PIL로 실행 파일에서 직접 아이콘 추출 시도
        try:
            # Windows 실행 파일의 아이콘 리소스를 추출
            import win32api
            import win32con

            # 아이콘 리소스 추출 (JUMBO 크기 포함)
            h = win32api.LoadLibraryEx(actual_path, 0, win32con.LOAD_LIBRARY_AS_DATAFILE)
            try:
                # 아이콘 그룹 리소스 찾기
                icon_ids = win32api.EnumResourceNames(h, win32con.RT_GROUP_ICON)
                if icon_ids:
                    # 첫 번째 아이콘 그룹 사용
                    group_data = win32api.LoadResource(h, win32con.RT_GROUP_ICON, icon_ids[0])

                    # 아이콘 그룹에서 가장 큰 아이콘 찾기
                    # 아이콘 그룹 구조: ICONDIR + ICONDIRENTRY[]
                    count = struct.unpack_from('<H', group_data, 4)[0]

                    best_icon_id = None
                    best_size = 0

                    for i in range(count):
                        offset = 6 + i * 14  # ICONDIRENTRY 시작 위치
                        width = group_data[offset]
                        height = group_data[offset + 1]
                        # 0은 256을 의미
                        size = width if width != 0 else 256
                        icon_id = struct.unpack_from('<H', group_data, offset + 12)[0]

                        if size > best_size:
                            best_size = size
                            best_icon_id = icon_id

                    # 가장 큰 아이콘 추출
                    if best_icon_id:
                        icon_data = win32api.LoadResource(h, win32con.RT_ICON, best_icon_id)

                        # PNG로 변환하여 저장
                        # 아이콘 데이터를 임시 파일로 저장 후 PIL로 열기
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix='.ico', delete=False) as tmp:
                            # ICO 파일 헤더 추가
                            tmp.write(b'\x00\x00\x01\x00\x01\x00')  # ICONDIR
                            tmp.write(struct.pack('<BBBBHHII',
                                best_size if best_size < 256 else 0,  # width
                                best_size if best_size < 256 else 0,  # height
                                0, 0, 1, 32,  # colors, reserved, planes, bpp
                                len(icon_data),  # size
                                22  # offset
                            ))
                            tmp.write(icon_data)
                            tmp_path = tmp.name

                        # PIL로 열어서 PNG로 저장
                        img = Image.open(tmp_path)
                        img.load()  # 이미지 데이터를 메모리에 로드
                        img.save(str(cache_path), 'PNG')
                        img.close()  # 파일 핸들 닫기

                        # 임시 파일 삭제
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass  # 삭제 실패는 무시 (임시 파일이므로)

                        return str(cache_path)
            finally:
                win32api.FreeLibrary(h)
        except Exception as e:
            print(f"고해상도 아이콘 추출 실패, 폴백 시도: {e}")

        # 방법 2: 폴백 - 기존 방식 (작은 아이콘)
        import win32gui
        import win32ui
        import win32con
        import win32api

        large_icons, small_icons = win32gui.ExtractIconEx(actual_path, 0)

        if large_icons:
            hicon = large_icons[0]

            # 원본 크기로 추출 (32x32)
            icon_size = 32
            hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
            hbmp = win32ui.CreateBitmap()
            hbmp.CreateCompatibleBitmap(hdc, icon_size, icon_size)

            hdc_mem = hdc.CreateCompatibleDC()
            hdc_mem.SelectObject(hbmp)
            hdc_mem.FillSolidRect((0, 0, icon_size, icon_size), win32api.RGB(0, 0, 0))

            win32gui.DrawIconEx(hdc_mem.GetHandleOutput(), 0, 0, hicon, icon_size, icon_size, 0, None, win32con.DI_NORMAL)

            # 비트맵 정보 추출
            bmpinfo = hbmp.GetInfo()
            bmpstr = hbmp.GetBitmapBits(True)

            # PIL Image로 변환
            img = Image.frombuffer(
                'RGBA',
                (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
                bmpstr, 'raw', 'BGRA', 0, 1
            )

            # PNG로 저장
            img.save(str(cache_path), 'PNG')

            # 정리
            for icon in large_icons + small_icons:
                win32gui.DestroyIcon(icon)

            return str(cache_path)

        return None

    except ImportError as e:
        print(f"아이콘 추출 모듈 없음: {e}")
        return None
    except Exception as e:
        print(f"아이콘 추출 실패 ({exe_path}): {e}")
        return None



def generate_fallback_svg(name: str, color: str) -> str:
    """폴백 SVG 아이콘 생성"""
    initial = name[0].upper() if name else "?"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
        <rect width="32" height="32" rx="6" fill="{color}"/>
        <text x="16" y="21" text-anchor="middle" fill="white" font-size="16" font-family="Arial" font-weight="bold">{initial}</text>
    </svg>'''
