"""
PyInstaller hook for PyAV (av)
PyAV의 C 확장 모듈과 DLL을 올바르게 수집
"""
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, collect_submodules

# PyAV의 모든 서브모듈 수집
hiddenimports = collect_submodules('av')

# PyAV의 바이너리 파일 (DLL) 수집
binaries = collect_dynamic_libs('av')

# PyAV의 데이터 파일 수집
datas = collect_data_files('av')
