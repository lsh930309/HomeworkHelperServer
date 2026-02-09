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
    """캐시된 아이콘 경로 반환"""
    return Path(ICON_CACHE_DIR) / f"{process_id}.png"


def extract_icon_from_exe(exe_path: str, process_id: str) -> str | None:
    """
    실행 파일에서 아이콘 추출
    
    Returns:
        캐시된 아이콘 파일 경로 또는 None
    """
    try:
        import win32gui
        import win32ui
        import win32con
        import win32api
        from PIL import Image
        
        ensure_cache_dir()
        cache_path = get_cached_icon_path(process_id)
        
        # 이미 캐시된 경우
        if cache_path.exists():
            return str(cache_path)
        
        # 실행 파일 존재 확인
        if not os.path.exists(exe_path):
            return None
        
        # 아이콘 추출
        large_icons, small_icons = win32gui.ExtractIconEx(exe_path, 0)
        
        if large_icons:
            hicon = large_icons[0]
            
            # 아이콘을 비트맵으로 변환
            hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
            hbmp = win32ui.CreateBitmap()
            hbmp.CreateCompatibleBitmap(hdc, 32, 32)
            
            hdc_mem = hdc.CreateCompatibleDC()
            hdc_mem.SelectObject(hbmp)
            hdc_mem.FillSolidRect((0, 0, 32, 32), win32api.RGB(0, 0, 0))
            
            win32gui.DrawIconEx(hdc_mem.GetHandleOutput(), 0, 0, hicon, 32, 32, 0, None, win32con.DI_NORMAL)
            
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
        
    except ImportError:
        # pywin32가 없는 경우
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
