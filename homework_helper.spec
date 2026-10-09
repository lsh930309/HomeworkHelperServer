# -*- mode: python ; coding: utf-8 -*-

# HomeworkHelper - PyInstaller spec (onedir 모드)
# Label Studio Helper 분리 후 정리된 버전

import sys
from pathlib import Path

from PyInstaller.utils.hooks.qt import pyside6_library_info

# The Windows wheel's platforminputcontexts contains only Qt Virtual Keyboard.
# QtGui's default hook collects it even for Widgets, pulling Quick/QML back into
# the binary dependency graph. Keep native platform, style, SVG and network
# plugins; exclude this unused QML input frontend at the collection boundary.
qt_gui_info = pyside6_library_info.python_modules['QtGui']
qt_gui_info.plugins = [
    plugin_type for plugin_type in qt_gui_info.plugins
    if plugin_type != 'platforminputcontexts'
]


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
            'api/dashboard/frontend',
            'api/dashboard/static',
            '**/__pycache__',
            '**/*.pyc',
            '**/tsconfig.tsbuildinfo',
        )),
        *collect_tree('build/dashboard-static', 'src/api/dashboard/static'),
    ],
    hiddenimports=[
        # FastAPI/Backend
        'uvicorn', 'fastapi', 'sqlalchemy', 'starlette',
        
        # GUI
        'PySide6', 'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui',
        'PySide6.QtNetwork',
        
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
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D',
        'PySide6.QtQuickControls2', 'PySide6.QtQuickTest', 'PySide6.QtQuickWidgets',
        'PySide6.QtWebEngineQuick',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# The service has its own import graph. It never imports the desktop entrypoint
# or database writer, and shares only immutable runtime binaries in onedir.
service_analysis = Analysis(
    ['homework_helper_service.py'],
    pathex=[], binaries=[], datas=[],
    hiddenimports=[
        'win32api', 'win32security', 'win32process', 'win32con', 'win32ts',
        'win32service', 'win32serviceutil', 'servicemanager',
        'win32pipe', 'win32file', 'win32event', 'pywintypes', 'psutil',
    ],
    excludes=['PySide6', 'fastapi', 'uvicorn', 'sqlalchemy', 'tkinter'],
    noarchive=False, optimize=0,
)
service_exe = EXE(
    PYZ(service_analysis.pure), service_analysis.scripts, [],
    exclude_binaries=True, name='homework_helper_service',
    debug=False, strip=False, upx=False, console=True,
    icon=['assets/icons/app/app_icon.ico'],
)

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
    service_exe,
    a.binaries,
    service_analysis.binaries,
    a.datas,
    service_analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='homework_helper'
)
