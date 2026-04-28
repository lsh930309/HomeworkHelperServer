# -*- mode: python ; coding: utf-8 -*-

# HomeworkHelper - PyInstaller spec (onedir 모드)
# Label Studio Helper 분리 후 정리된 버전

import sys
from pathlib import Path


def collect_tree(src, dest, excludes=()):
    src_path = Path(src)
    rows = []
    for path in src_path.rglob('*'):
        rel = path.relative_to(src_path)
        rel_posix = rel.as_posix()
        if path.is_dir():
            continue
        if any(path.match(pattern) or rel_posix.startswith(pattern.rstrip('/') + '/') for pattern in excludes):
            continue
        rows.append((str(path), str(Path(dest) / rel.parent)))
    return rows

a = Analysis(
    ['homework_helper.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        *collect_tree('assets', 'assets'),
        *collect_tree('src', 'src', excludes=(
            'api/dashboard/frontend/node_modules',
            '**/__pycache__',
            '**/*.pyc',
            '**/tsconfig.tsbuildinfo',
        )),
    ],
    hiddenimports=[
        # FastAPI/Backend
        'uvicorn', 'fastapi', 'sqlalchemy', 'starlette',
        
        # GUI
        'PyQt6', 'PyQt6.QtWidgets', 'PyQt6.QtCore', 'PyQt6.QtGui',
        
        # Windows
        'win32api', 'win32security', 'win32process', 'win32con', 'win32com.client',
        'winshell', 'psutil',
        
        # Network
        'requests',
        'websocket', 'websocket._app', 'websocket._core', 'websocket._http',
        
        # Data
        'pydantic', 'jsonschema',

        # Audio (pycaw - Windows WASAPI)
        'pycaw', 'pycaw.pycaw',
        'comtypes', 'comtypes.client',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PyTorch 관련 (LSH로 이동)
        'torch', 'torchvision', 'torchaudio',
        
        # 영상/이미지 처리 (LSH로 이동)
        'cv2', 'av', 'skimage', 'scipy', 'matplotlib',
        'numpy', 'imageio',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='homework_helper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icons/app/app_icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='homework_helper'
)
