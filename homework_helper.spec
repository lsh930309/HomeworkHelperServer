# -*- mode: python ; coding: utf-8 -*-

# HomeworkHelper - PyInstaller spec (onedir 모드)
# Label Studio Helper 분리 후 정리된 버전

import sys
from pathlib import Path

a = Analysis(
    ['homework_helper.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets', 'assets'),
        ('src', 'src'),
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
        
        # Data
        'pydantic', 'jsonschema',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PyTorch 관련 (LSH로 이동)
        'torch', 'torchvision', 'torchaudio',
        
        # 영상/이미지 처리 (LSH로 이동)
        'cv2', 'av', 'skimage', 'scipy', 'PIL', 'matplotlib',
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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='homework_helper'
)
