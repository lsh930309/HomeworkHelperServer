#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PyInstaller 자동 빌드 스크립트 (GUI 버전)
- tkinter GUI로 버전 선택 및 빌드 진행 표시
- 시스템 다크/라이트 모드 자동 감지
- 기존 build.py의 모든 기능 유지
"""

import os
import sys
import shutil
import subprocess
import zipfile
import re
import threading
import queue
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext
from tkinter import font as tkfont

# ==================== 설정 ====================
PROJECT_ROOT = Path(__file__).parent
RELEASE_DIR = PROJECT_ROOT / "release"
ARCHIVES_DIR = RELEASE_DIR / "archives"
BUILD_DIR = PROJECT_ROOT / "build"
DIST_DIR = PROJECT_ROOT / "dist"

SPEC_FILE = PROJECT_ROOT / "homework_helper.spec"
APP_NAME = "homework_helper"
APP_FOLDER = DIST_DIR / APP_NAME

INNO_SETUP_PATH = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
INSTALLER_SCRIPT = PROJECT_ROOT / "installer.iss"

VERSION_PATTERN = re.compile(r'v(\d+)\.(\d+)\.(\d+)\.(\d{12})')

# 폰트 경로
FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "NEXONLv1GothicOTFBold.otf"
# ================================================


def load_custom_font():
    """커스텀 폰트 로딩"""
    if FONT_PATH.exists():
        try:
            # Windows에서 폰트 등록
            import ctypes
            ctypes.windll.gdi32.AddFontResourceW(str(FONT_PATH))
            return "NEXON Lv1 Gothic OTF Bold"
        except (OSError, ImportError, AttributeError) as e:
            print(f"[경고] 커스텀 폰트 로딩 실패: {e}")
    return "맑은 고딕"  # 폴백 폰트


def is_dark_mode():
    """Windows 다크 모드 감지"""
    try:
        import winreg
        registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
        key = winreg.OpenKey(
            registry,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0  # 0 = 다크 모드, 1 = 라이트 모드
    except (FileNotFoundError, OSError, PermissionError) as e:
        print(f"[경고] 다크 모드 감지 실패: {e}")
        return False  # 기본값: 라이트 모드


class ThemeColors:
    """테마 색상 정의"""
    def __init__(self, dark_mode=False):
        if dark_mode:
            self.bg = '#1e1e1e'
            self.fg = '#ffffff'
            self.input_bg = '#2d2d2d'
            self.input_fg = '#ffffff'
            self.button_bg = '#0e639c'
            self.button_fg = '#ffffff'
            self.log_bg = '#1e1e1e'
            self.log_fg = '#cccccc'
            self.highlight_bg = '#094771'
            self.border = '#3e3e3e'
            self.success = '#4ec9b0'
            self.error = '#f48771'
            self.warning = '#ce9178'
        else:
            self.bg = '#f0f0f0'
            self.fg = '#000000'
            self.input_bg = '#ffffff'
            self.input_fg = '#000000'
            self.button_bg = '#0078d4'
            self.button_fg = '#ffffff'
            self.log_bg = '#ffffff'
            self.log_fg = '#000000'
            self.highlight_bg = '#cce8ff'
            self.border = '#d0d0d0'
            self.success = '#107c10'
            self.error = '#d13438'
            self.warning = '#ff8c00'


def get_latest_version():
    """release 폴더에서 최신 버전 찾기"""
    if not RELEASE_DIR.exists():
        return None

    latest_version = None
    for file_path in RELEASE_DIR.glob("HomeworkHelper_v*"):
        match = VERSION_PATTERN.search(file_path.name)
        if match:
            major, minor, patch, timestamp = match.groups()
            version_tuple = (int(major), int(minor), int(patch), timestamp)
            if latest_version is None or version_tuple > latest_version:
                latest_version = version_tuple

    if latest_version:
        major, minor, patch, timestamp = latest_version
        return {
            'major': major,
            'minor': minor,
            'patch': patch,
            'timestamp': timestamp,
            'string': f"v{major}.{minor}.{patch}.{timestamp}"
        }
    return None


class VersionSelectorGUI:
    """버전 선택 GUI"""

    def __init__(self, latest_version, theme, font_family="맑은 고딕"):
        self.latest_version = latest_version
        self.theme = theme
        self.font_family = font_family
        self.result = None

        if latest_version:
            self.current = [latest_version['major'], latest_version['minor'], latest_version['patch']]
            self.original = self.current.copy()
        else:
            self.current = [1, 0, 0]
            self.original = self.current.copy()

        self.position = 0  # 0=major, 1=minor, 2=patch

        # 창 생성
        self.root = tk.Tk()
        self.root.title("HomeworkHelper - 버전 선택")
        self.root.geometry("450x320")
        self.root.resizable(False, False)
        self.root.configure(bg=theme.bg)

        # 항상 최상위
        self.root.attributes('-topmost', True)

        self._create_widgets()
        self._bind_events()

    def _create_widgets(self):
        """위젯 생성"""
        # 제목
        title = tk.Label(
            self.root,
            text="버전 선택",
            font=(self.font_family, 16),
            bg=self.theme.bg,
            fg=self.theme.fg
        )
        title.pack(pady=15)

        # 최신 버전 표시
        if self.latest_version:
            info = tk.Label(
                self.root,
                text=f"최신 버전: {self.latest_version['string']}",
                font=(self.font_family, 9),
                bg=self.theme.bg,
                fg=self.theme.fg
            )
            info.pack(pady=5)

        # 버전 표시 프레임
        version_frame = tk.Frame(self.root, bg=self.theme.bg)
        version_frame.pack(pady=25)

        # 버전 라벨들
        self.labels = []
        for i in range(3):
            label = tk.Label(
                version_frame,
                text=str(self.current[i]),
                font=(self.font_family, 32),
                width=3,
                bg=self.theme.highlight_bg if i == 0 else self.theme.input_bg,
                fg=self.theme.fg,
                relief=tk.FLAT,  # 플랫 디자인
                borderwidth=1
            )
            label.pack(side=tk.LEFT, padx=5)
            self.labels.append(label)

            if i < 2:
                dot = tk.Label(
                    version_frame,
                    text=".",
                    font=(self.font_family, 32),
                    bg=self.theme.bg,
                    fg=self.theme.fg
                )
                dot.pack(side=tk.LEFT)

        # 조작 안내
        help_frame = tk.Frame(self.root, bg=self.theme.bg)
        help_frame.pack(pady=20)

        help_items = [
            ("← →", "자릿수 이동"),
            ("↑ ↓", "숫자 증감"),
            ("Enter", "확정"),
            ("ESC", "취소")
        ]

        for i, (key, desc) in enumerate(help_items):
            row = i // 2
            col = i % 2

            key_label = tk.Label(
                help_frame,
                text=key,
                font=(self.font_family, 9),
                bg=self.theme.input_bg,
                fg=self.theme.fg,
                relief=tk.FLAT,  # 플랫 디자인
                borderwidth=1,
                padx=8,
                pady=2
            )
            key_label.grid(row=row, column=col*2, padx=5, pady=3, sticky='e')

            desc_label = tk.Label(
                help_frame,
                text=desc,
                font=(self.font_family, 9),
                bg=self.theme.bg,
                fg=self.theme.fg
            )
            desc_label.grid(row=row, column=col*2+1, padx=5, pady=3, sticky='w')

    def _update_display(self):
        """버전 표시 업데이트"""
        for i, label in enumerate(self.labels):
            is_selected = (i == self.position)
            label.config(
                text=str(self.current[i]),
                bg=self.theme.highlight_bg if is_selected else self.theme.input_bg
            )

    def _bind_events(self):
        """키보드 이벤트 바인딩"""
        self.root.bind('<Left>', self._on_left)
        self.root.bind('<Right>', self._on_right)
        self.root.bind('<Up>', self._on_up)
        self.root.bind('<Down>', self._on_down)
        self.root.bind('<Return>', self._on_enter)
        self.root.bind('<Escape>', self._on_escape)

    def _on_left(self, event):
        self.position = max(0, self.position - 1)
        self._update_display()

    def _on_right(self, event):
        self.position = min(2, self.position + 1)
        self._update_display()

    def _on_up(self, event):
        old_value = self.current[self.position]
        self.current[self.position] += 1

        # major 증가 시 minor, patch 초기화
        if self.position == 0 and self.current[0] > old_value:
            self.current[1] = 0
            self.current[2] = 0
        # minor 증가 시 patch 초기화
        elif self.position == 1 and self.current[1] > old_value:
            self.current[2] = 0

        self._update_display()

    def _on_down(self, event):
        new_value = self.current.copy()
        new_value[self.position] = max(0, self.current[self.position] - 1)

        # 감소 후 버전이 원본보다 작아지는지 확인
        if tuple(new_value) >= tuple(self.original):
            self.current[self.position] = new_value[self.position]
            self._update_display()

    def _on_enter(self, event):
        # 버전 검증
        if tuple(self.current) < tuple(self.original):
            # 오류 메시지 표시
            error_label = tk.Label(
                self.root,
                text="⚠ 이전 버전보다 낮은 버전은 설정할 수 없습니다",
                font=(self.font_family, 9),
                bg=self.theme.bg,
                fg=self.theme.error
            )
            error_label.pack(pady=5)
            self.root.after(2000, error_label.destroy)
            return

        timestamp = datetime.now().strftime("%y%m%d%H%M%S")
        self.result = {
            'major': self.current[0],
            'minor': self.current[1],
            'patch': self.current[2],
            'timestamp': timestamp,
            'string': f"v{self.current[0]}.{self.current[1]}.{self.current[2]}.{timestamp}"
        }
        self.root.destroy()

    def _on_escape(self, event):
        self.root.destroy()

    def show(self):
        """창 표시 및 결과 반환"""
        self.root.focus_force()
        self.root.mainloop()
        return self.result


class BuildProgressGUI:
    """빌드 진행 상황 GUI"""

    def __init__(self, version_info, theme, font_family="맑은 고딕"):
        self.version_info = version_info
        self.theme = theme
        self.font_family = font_family

        # 창 생성 (작고 깔끔하게)
        self.root = tk.Tk()
        self.root.title("HomeworkHelper 빌드")
        self.root.geometry("500x210")  # 세로 높이 증가 (180 → 210)
        self.root.resizable(False, False)
        self.root.configure(bg=theme.bg)

        # 항상 최상위
        self.root.attributes('-topmost', True)

        # 애니메이션 상태
        self.status_base = ""
        self.animation_dots = 1
        self.is_animating = True

        self._create_widgets()
        self._start_animation()

    def _create_widgets(self):
        """위젯 생성"""
        # 메인 프레임
        main_frame = tk.Frame(self.root, bg=self.theme.bg)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=20)

        # 제목
        title = tk.Label(
            main_frame,
            text="HomeworkHelper 빌드",
            font=(self.font_family, 16),
            bg=self.theme.bg,
            fg=self.theme.fg
        )
        title.pack(pady=(0, 5))

        # 버전 정보
        version_label = tk.Label(
            main_frame,
            text=f"버전: {self.version_info['string']}",
            font=(self.font_family, 10),
            bg=self.theme.bg,
            fg=self.theme.fg
        )
        version_label.pack(pady=(0, 15))

        # 진행 상태
        self.status_label = tk.Label(
            main_frame,
            text="준비 중...",
            font=(self.font_family, 11),
            bg=self.theme.bg,
            fg=self.theme.fg
        )
        self.status_label.pack(pady=(0, 10))

        # 프로그레스 바 (Windows 스타일 녹색, 플랫)
        style = ttk.Style()
        style.theme_use('clam')  # 플랫한 스타일
        style.configure(
            "Green.Horizontal.TProgressbar",
            troughcolor=self.theme.input_bg,
            bordercolor=self.theme.border,
            background='#06b025',  # Windows 녹색
            lightcolor='#06b025',
            darkcolor='#06b025',
            thickness=24
        )

        self.progress = ttk.Progressbar(
            main_frame,
            mode='determinate',
            maximum=100,
            style="Green.Horizontal.TProgressbar"
        )
        self.progress.pack(fill=tk.X, pady=(0, 10))
        self.progress['value'] = 0

        # 진행률 퍼센트 표시
        self.percent_label = tk.Label(
            main_frame,
            text="0%",
            font=(self.font_family, 12),
            bg=self.theme.bg,
            fg=self.theme.fg
        )
        self.percent_label.pack()

    def _start_animation(self):
        """상태 메시지 점 애니메이션 시작"""
        def update_animation():
            if self.is_animating and self.status_base.endswith(" 중"):
                dots = "." * self.animation_dots
                self.status_label.config(text=f"{self.status_base}{dots}")
                self.animation_dots = (self.animation_dots % 3) + 1
            self.root.after(500, update_animation)  # 0.5초마다 업데이트

        self.root.after(500, update_animation)

    def _is_main_thread(self):
        """현재 스레드가 메인 스레드인지 확인"""
        import threading
        return threading.current_thread() == threading.main_thread()

    def _safe_call(self, func):
        """스레드-안전 GUI 호출"""
        if self._is_main_thread():
            func()
        else:
            self.root.after(0, func)

    def log(self, message, tag='', update_last_line=False):
        """로그 메시지 (더미 - 로그 박스 제거됨)"""
        pass  # 로그 출력 안함

    def log_section(self, title):
        """섹션 제목 로그 (더미)"""
        pass  # 로그 출력 안함

    def set_status(self, status):
        """상태 메시지 업데이트 (스레드-안전)"""
        def _update():
            # 끝의 점들을 제거하여 기본 메시지 저장
            self.status_base = status.rstrip('.')

            # "~~~ 중..." 형태면 애니메이션 활성화
            if self.status_base.endswith(" 중"):
                self.is_animating = True
                self.animation_dots = 1  # 리셋
            else:
                # 완료 메시지 등은 애니메이션 비활성화
                self.is_animating = False
                self.status_label.config(text=status)

        self._safe_call(_update)

    def set_progress(self, value):
        """프로그레스 바 값 설정 (0~100, 스레드-안전)"""
        def _update():
            self.progress['value'] = value
            self.percent_label.config(text=f"{int(value)}%")
            self.root.update_idletasks()

        self._safe_call(_update)

    def show_complete(self, success=True, auto_close_delay=3000):
        """완료 표시 및 자동 종료 (스레드-안전)"""
        def _complete():
            self.progress['value'] = 100
            self.percent_label.config(text="100%")
            self.root.update_idletasks()

            if success:
                self.status_base = "✓ 빌드 완료! (잠시 후 자동 종료...)"
                self.is_animating = False
                self.status_label.config(text=self.status_base)
                # 자동 종료
                if auto_close_delay > 0:
                    self.root.after(auto_close_delay, self.root.destroy)
            else:
                self.status_base = "✗ 빌드 실패"
                self.is_animating = False
                self.status_label.config(text=self.status_base)

        self._safe_call(_complete)


# ==================== 빌드 함수들 ====================

def archive_old_files(gui, _new_version):
    """이전 버전 파일들을 archives 폴더로 이동"""
    gui.log_section("이전 버전 파일 아카이빙")
    gui.set_status("이전 버전 파일 아카이빙 중...")
    gui.set_progress(5)

    if not RELEASE_DIR.exists():
        gui.log("  (이전 버전 파일 없음)")
        return

    date_folder = datetime.now().strftime("%y-%m-%d")
    files_to_archive = []

    for file_path in RELEASE_DIR.glob("HomeworkHelper_v*"):
        if file_path.is_file() and file_path.suffix in ['.exe', '.zip']:
            files_to_archive.append(file_path)

    if not files_to_archive:
        gui.log("  (아카이빙할 파일 없음)")
        return

    archived_count = 0
    for file_path in files_to_archive:
        if file_path.suffix == '.exe':
            archive_subdir = ARCHIVES_DIR / "installer" / date_folder
        elif file_path.suffix == '.zip':
            archive_subdir = ARCHIVES_DIR / "portable" / date_folder
        else:
            continue

        archive_subdir.mkdir(parents=True, exist_ok=True)
        dest = archive_subdir / file_path.name
        shutil.move(str(file_path), str(dest))
        archived_count += 1
        gui.log(f"  ✓ {file_path.name} → archives/{file_path.suffix[1:]}/{date_folder}/")

    gui.log(f"\n총 {archived_count}개 파일 아카이빙 완료", 'success')
    gui.set_progress(10)


def clean_build_artifacts(gui):
    """빌드 산출물 폴더 삭제"""
    gui.log_section("이전 빌드 산출물 정리")
    gui.set_status("이전 빌드 산출물 정리 중...")
    gui.set_progress(15)

    for folder in [BUILD_DIR, DIST_DIR]:
        if folder.exists():
            try:
                shutil.rmtree(folder)
                gui.log(f"  ✓ 삭제: {folder.name}/", 'success')
            except Exception as e:
                gui.log(f"  ⚠ 삭제 실패 ({folder.name}): {e}", 'warning')
        else:
            gui.log(f"  (없음: {folder.name}/)")

    gui.set_progress(20)


def ensure_release_dir(gui):
    """release 폴더 생성"""
    if not RELEASE_DIR.exists():
        RELEASE_DIR.mkdir(parents=True, exist_ok=True)
        gui.log("  ✓ release 폴더 생성", 'success')
    return RELEASE_DIR


def build_with_pyinstaller(gui):
    """PyInstaller로 빌드"""
    gui.log_section("PyInstaller 빌드 시작 (onedir 모드)")
    gui.set_status("PyInstaller 빌드 중...")
    gui.set_progress(25)

    if not SPEC_FILE.exists():
        gui.log(f"✗ .spec 파일 없음: {SPEC_FILE}", 'error')
        return False

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
        "--clean",
    ]

    gui.log(f"빌드 명령: {' '.join(cmd)}\n")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=PROJECT_ROOT,
            bufsize=1
        )

        line_count = 0
        last_was_progress = False

        # 진행률 패턴 (같은 줄 업데이트 대상)
        progress_patterns = [
            'building',
            'copying',
            'compressing',
            'EXE',
            'Appending',
            'Processing',
        ]

        for line in iter(process.stdout.readline, ''):
            if line.strip():
                cleaned_line = line.replace('\r', '').strip()

                # 진행률 메시지인지 판단
                is_progress = any(pattern in cleaned_line for pattern in progress_patterns)

                if is_progress and last_was_progress and line_count > 0:
                    # 이전 줄도 진행률이었다면 덮어쓰기
                    gui.log(f"  → {cleaned_line}", update_last_line=True)
                else:
                    # 새 줄로 추가
                    gui.log(f"  → {cleaned_line}")

                last_was_progress = is_progress
                line_count += 1

                # 진행률 업데이트 (25% ~ 60%)
                progress = min(60, 25 + (line_count * 0.3))
                gui.set_progress(progress)

        process.wait()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)

        gui.log("\n✓ PyInstaller 빌드 성공!", 'success')
        gui.set_progress(60)
        return True
    except subprocess.CalledProcessError as e:
        gui.log(f"\n✗ 빌드 실패: {e}", 'error')
        return False


def create_zip_distribution(gui, version_info):
    """ZIP 배포 파일 생성"""
    gui.log_section("ZIP 배포 파일 생성")
    gui.set_status("ZIP 파일 생성 중...")
    gui.set_progress(65)

    if not APP_FOLDER.exists():
        gui.log(f"✗ 배포 폴더 없음: {APP_FOLDER}", 'error')
        return False

    ensure_release_dir(gui)
    zip_filename = f"HomeworkHelper_{version_info['string']}_Portable.zip"
    zip_path = RELEASE_DIR / zip_filename

    try:
        gui.log("파일 목록 수집 중...")
        all_files = []
        for root, dirs, files in os.walk(APP_FOLDER):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(DIST_DIR)
                all_files.append((file_path, arcname))

        gui.log(f"총 {len(all_files)}개 파일 압축 중...")

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, (file_path, arcname) in enumerate(all_files):
                zipf.write(file_path, arcname)

                # 진행률 업데이트 (65% ~ 75%)
                if i % 10 == 0:
                    progress = 65 + (i / len(all_files) * 10)
                    gui.set_progress(progress)
                    gui.log(f"  압축 중: {i}/{len(all_files)} 파일...", update_last_line=(i > 0))

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        gui.log(f"\n✓ ZIP 생성 완료: {zip_filename}", 'success')
        gui.log(f"  파일 크기: {size_mb:.2f} MB")
        gui.log(f"  저장 위치: {zip_path}")
        gui.set_progress(75)
        return True
    except Exception as e:
        gui.log(f"✗ ZIP 생성 실패: {e}", 'error')
        return False


def update_installer_script_version(version_info):
    """installer.iss 파일의 버전 정보 업데이트"""
    if not INSTALLER_SCRIPT.exists():
        return False

    try:
        with open(INSTALLER_SCRIPT, 'r', encoding='utf-8') as f:
            content = f.read()

        version_string = f"{version_info['major']}.{version_info['minor']}.{version_info['patch']}"
        content = re.sub(
            r'(#define MyAppVersion\s+")[^"]+(")',
            rf'\g<1>{version_string}\g<2>',
            content
        )

        with open(INSTALLER_SCRIPT, 'w', encoding='utf-8') as f:
            f.write(content)

        return True
    except Exception as e:
        return False


def create_installer(gui, version_info):
    """Inno Setup으로 인스톨러 생성"""
    gui.log_section("Inno Setup 인스톨러 생성")
    gui.set_status("인스톨러 생성 중...")
    gui.set_progress(80)

    if not INNO_SETUP_PATH.exists():
        gui.log("⚠ Inno Setup이 설치되어 있지 않습니다", 'warning')
        gui.log(f"  예상 경로: {INNO_SETUP_PATH}")
        gui.log("  다운로드: https://jrsoftware.org/isinfo.php")
        gui.set_progress(95)  # 건너뛰기
        return False

    if not INSTALLER_SCRIPT.exists():
        gui.log(f"✗ 인스톨러 스크립트 없음: {INSTALLER_SCRIPT}", 'error')
        return False

    if not APP_FOLDER.exists():
        gui.log(f"✗ 배포 폴더 없음: {APP_FOLDER}", 'error')
        return False

    update_installer_script_version(version_info)

    cmd = [str(INNO_SETUP_PATH), str(INSTALLER_SCRIPT)]
    gui.log(f"인스톨러 명령: {' '.join(cmd)}\n")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=PROJECT_ROOT,
            bufsize=1
        )

        line_count = 0
        last_was_progress = False

        # Inno Setup 진행률 패턴
        progress_patterns = [
            'Compiling',
            'Preprocessing',
            'Compressing',
            'Creating',
            '%',  # 퍼센트 포함
        ]

        for line in iter(process.stdout.readline, ''):
            if line.strip():
                cleaned_line = line.replace('\r', '').strip()

                # 진행률 메시지인지 판단
                is_progress = any(pattern in cleaned_line for pattern in progress_patterns)

                if is_progress and last_was_progress and line_count > 0:
                    # 이전 줄도 진행률이었다면 덮어쓰기
                    gui.log(f"  → {cleaned_line}", update_last_line=True)
                else:
                    # 새 줄로 추가
                    gui.log(f"  → {cleaned_line}")

                last_was_progress = is_progress
                line_count += 1

                # 진행률 업데이트 (80% ~ 95%)
                progress = min(95, 80 + (line_count * 0.3))
                gui.set_progress(progress)

        process.wait()

        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)

        gui.log("\n✓ 인스톨러 생성 성공!", 'success')

        # 파일명 변경
        base_version = f"{version_info['major']}.{version_info['minor']}.{version_info['patch']}"
        expected_filename = f"HomeworkHelper_Setup_v{base_version}.exe"
        generated_file = RELEASE_DIR / expected_filename

        if generated_file.exists():
            new_name = f"HomeworkHelper_{version_info['string']}_Setup.exe"
            dest = RELEASE_DIR / new_name
            shutil.move(str(generated_file), str(dest))

            size_mb = dest.stat().st_size / (1024 * 1024)
            gui.log(f"  인스톨러: {new_name} ({size_mb:.2f} MB)")
            gui.log(f"  저장 위치: {dest}")
        else:
            gui.log(f"✗ 생성된 인스톨러 파일을 찾을 수 없습니다: {expected_filename}", 'error')
            return False

        gui.set_progress(95)
        return True
    except subprocess.CalledProcessError as e:
        gui.log(f"\n✗ 인스톨러 생성 실패: {e}", 'error')
        return False


def print_summary(gui, version_info):
    """빌드 결과 요약"""
    gui.log_section("빌드 완료 - 결과 요약")
    gui.set_progress(98)

    gui.log(f"\n빌드 버전: {version_info['string']}")
    gui.log("\n배포 파일 목록 (release 폴더):")
    gui.log("-" * 70)

    if not RELEASE_DIR.exists():
        gui.log("  (release 폴더 없음)")
        return

    has_files = False

    # 인스톨러
    for setup_file in RELEASE_DIR.glob(f"*{version_info['string']}*Setup*.exe"):
        size_mb = setup_file.stat().st_size / (1024 * 1024)
        gui.log(f"  [인스톨러] {setup_file.name} ({size_mb:.2f} MB)", 'success')
        has_files = True

    # ZIP
    for zip_file in RELEASE_DIR.glob(f"*{version_info['string']}*Portable*.zip"):
        size_mb = zip_file.stat().st_size / (1024 * 1024)
        gui.log(f"  [Portable] {zip_file.name} ({size_mb:.2f} MB)", 'success')
        has_files = True

    if not has_files:
        gui.log("  (파일 없음)")

    gui.log("-" * 70)
    gui.log(f"\n배포 경로: {RELEASE_DIR.absolute()}")
    gui.log("\n사용 방법:")
    gui.log("  1. 설치 프로그램: *Setup*.exe 실행")
    gui.log("  2. Portable 버전: *.zip 압축 해제 후 실행")


def run_build_process(gui, version_info):
    """빌드 프로세스 실행 (별도 스레드)"""
    def build():
        try:
            # 1. 아카이빙
            archive_old_files(gui, version_info)

            # 2. 정리
            clean_build_artifacts(gui)

            # 3. PyInstaller 빌드
            if not build_with_pyinstaller(gui):
                gui.show_complete(False, auto_close_delay=0)  # 실패 시 자동 종료 안함
                return

            # 4. ZIP 생성
            success_count = 0
            if create_zip_distribution(gui, version_info):
                success_count += 1

            # 5. 인스톨러 생성
            if create_installer(gui, version_info):
                success_count += 1

            # 6. 결과 요약
            print_summary(gui, version_info)

            if success_count == 0:
                gui.log("\n⚠ 배포 파일이 생성되지 않았습니다.", 'warning')
                gui.show_complete(False, auto_close_delay=0)
                return

            # 7. release 폴더 열기
            folder_opened = False
            try:
                subprocess.Popen(['explorer', str(RELEASE_DIR.absolute())])
                gui.log("\n✓ release 폴더를 열었습니다", 'success')
                folder_opened = True
            except Exception as e:
                gui.log(f"\n⚠ release 폴더 열기 실패: {e}", 'warning')

            # 8. 완료 (폴더 열기 성공 시만 자동 종료)
            if folder_opened:
                gui.show_complete(True, auto_close_delay=3000)  # 3초 후 자동 종료
            else:
                gui.show_complete(True, auto_close_delay=0)  # 수동 종료

        except Exception as e:
            gui.log(f"\n✗ 예상치 못한 오류: {e}", 'error')
            import traceback
            gui.log(traceback.format_exc(), 'error')
            gui.show_complete(False, auto_close_delay=0)

    # 빌드 스레드 시작
    build_thread = threading.Thread(target=build, daemon=True)
    build_thread.start()


def main():
    """메인 함수"""
    # 커스텀 폰트 로딩
    font_family = load_custom_font()

    # 다크 모드 감지
    dark_mode = is_dark_mode()
    theme = ThemeColors(dark_mode)

    # .spec 파일 존재 확인
    if not SPEC_FILE.exists():
        print(f"[오류] {SPEC_FILE.name} 파일을 찾을 수 없습니다.")
        return 1

    # 1. 최신 버전 확인
    latest_version = get_latest_version()

    # 2. 버전 선택 GUI
    version_selector = VersionSelectorGUI(latest_version, theme, font_family)
    version_info = version_selector.show()

    if version_info is None:
        print("[취소] 빌드를 중단합니다.")
        return 1

    # 3. 빌드 진행 GUI
    build_gui = BuildProgressGUI(version_info, theme, font_family)

    # 4. 빌드 프로세스 시작
    run_build_process(build_gui, version_info)

    # GUI 실행
    build_gui.root.mainloop()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[중단] 사용자에 의해 중단됨")
        sys.exit(1)
    except Exception as e:
        print(f"\n[오류] 예상치 못한 오류: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
