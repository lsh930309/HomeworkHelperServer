# -*- mode: python ; coding: utf-8 -*-

# onedir 모드: 모든 파일을 폴더에 배포하여 MEI 임시 폴더 문제 해결

a = Analysis(
    ['homework_helper.pyw'],
    pathex=[],
    binaries=[],
    datas=[('font', 'font'), ('img', 'img'), ('src', 'src')],
    hiddenimports=['uvicorn', 'fastapi', 'sqlalchemy', 'requests', 'PyQt6', 'psutil', 'win32api', 'win32security', 'win32process', 'win32con', 'win32com.client'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
