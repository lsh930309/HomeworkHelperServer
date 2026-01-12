# -*- mode: python ; coding: utf-8 -*-

# onedir 모드: 모든 파일을 폴더에 배포하여 MEI 임시 폴더 문제 해결

import sys
from pathlib import Path

# Python 표준 라이브러리 경로 (가상환경이 아닌 실제 Python 경로)
python_lib = Path(sys.base_prefix) / 'Lib'

a = Analysis(
    ['homework_helper.pyw'],
    pathex=[],
    binaries=[],
    datas=[
        ('font', 'font'),
        ('img', 'img'),
        ('src', 'src'),
        ('label-studio', 'label-studio'),
        ('tools', 'tools'),
        ('schemas', 'schemas'),
        # Python 표준 라이브러리 (PyTorch import에 필수)
        (str(python_lib / 'modulefinder.py'), 'Lib'),
        (str(python_lib / 'importlib'), 'Lib/importlib'),
        (str(python_lib / 'pkgutil.py'), 'Lib'),
        (str(python_lib / 'inspect.py'), 'Lib'),
        (str(python_lib / 'dis.py'), 'Lib'),
        (str(python_lib / 'opcode.py'), 'Lib'),
        (str(python_lib / 'ast.py'), 'Lib'),
    ],
    hiddenimports=[
        # 기본 의존성
        'uvicorn', 'fastapi', 'sqlalchemy', 'requests', 'PyQt6', 'psutil',
        'win32api', 'win32security', 'win32process', 'win32con', 'win32com.client',
        'cv2', 'av', 'skimage', 'skimage.metrics', 'skimage._shared', 'skimage._shared.utils',
        'timeit', 'pickletools', 'pickle', 'copyreg', 'types', 'weakref', 'struct', 'matplotlib',
        # Python 표준 라이브러리 (PyTorch import에 필수)
        'modulefinder', 'importlib', 'importlib.util', 'importlib.machinery',
        'importlib.metadata', 'importlib.resources', 'importlib.abc',
        'pkgutil', 'inspect', 'typing', 'typing_extensions',
        'collections', 'collections.abc', 'functools', 'operator', 'itertools',
        'contextlib', 'warnings', 'dis', 'opcode', 'token', 'tokenize',
        'linecache', 'traceback', 'ast', 'keyword', 'reprlib',
        # 추가 표준 라이브러리
        'io', 'sys', 'os', 'os.path', 'pathlib', 're', 'json', 'math',
        'platform', 'subprocess', 'threading', 'queue', 'time', 'datetime',
        'email', 'email.mime', 'email.mime.text', 'mimetypes'
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['hooks/runtime_hook_stdlib.py'],
    excludes=['torch', 'torchvision', 'torchaudio', 'torch.nn', 'torch.cuda', 'torch.distributed', 'torch.optim', 'torch.utils', 'torch.jit', 'torch.autograd'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# EXE: onedir 모드에서는 실행 파일만 생성
exe = EXE(
    pyz,
    a.scripts,
    [],  # onefile과 다른 점: binaries, datas 제거
    exclude_binaries=True,  # 중요: 별도 수집하도록 지정
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
    icon=['img/app_icon.ico'],
)

# COLLECT: 모든 파일을 하나의 폴더에 수집 (onedir의 핵심)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='homework_helper'  # 최종 폴더: dist/homework_helper/
)
