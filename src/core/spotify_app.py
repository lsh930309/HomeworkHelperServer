"""지정 사용자의 Spotify 실행 관측과 한 번의 비활성 실행 요청.

앱의 존재와 GSMTC 준비는 다른 사실이다. 프로세스 관측은 실행 중복을
피하는 데만 쓰며, 실제 재생 가능 여부는 미디어 세션이 소유한다.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import ntpath
import os
import sys


SPOTIFY_DJ_URI = "spotify:playlist:37i9dQZF1EYkqdzj48dyYq"


@dataclass(frozen=True)
class SpotifyProcess:
    pid: int
    create_time: float
    path: str


@dataclass(frozen=True)
class SpotifyWindow:
    process: SpotifyProcess
    hwnd: int


def _spotify_executable(path: str, *, appdata: str | None = None, local_appdata: str | None = None) -> bool:
    path = ntpath.normcase(ntpath.normpath(path))
    roots = (
        (os.environ.get("APPDATA", "") if appdata is None else appdata, "Spotify"),
        (os.environ.get("LOCALAPPDATA", "") if local_appdata is None else local_appdata, "Spotify"),
        (os.environ.get("ProgramFiles", ""), "Spotify"),
        (os.environ.get("ProgramFiles(x86)", ""), "Spotify"),
    )
    if any(root and path == ntpath.normcase(ntpath.join(root, folder, "Spotify.exe"))
           for root, folder in roots):
        return True
    # Store 패키지 버전은 갱신되므로 특정 WindowsApps 버전 경로를 고정하지 않는다.
    program_files = os.environ.get("ProgramFiles", "")
    if not program_files or ntpath.basename(path) != "spotify.exe":
        return False
    store = ntpath.normcase(ntpath.join(program_files, "WindowsApps")) + "\\"
    if not path.startswith(store):
        return False
    relative = path[len(store):].split("\\")
    return (len(relative) == 2 and relative[0].startswith("spotifyab.spotifymusic_")
            and relative[0].endswith("__zpdnekdrzrea0"))


def spotify_processes(*, appdata: str | None = None, local_appdata: str | None = None) -> tuple[SpotifyProcess, ...]:
    """실행 중인 현재 사용자·Windows 세션의 실제 Spotify만 반환한다.

    이름이 같은 임의 EXE·다른 사용자·상주 launcher는 실행 완료의 근거가 아니다.
    해당 Spotify의 조회 실패를 미실행으로 바꿔 중복 실행하지 않는다.
    """
    if sys.platform != "win32":
        raise OSError("Spotify process observation requires Windows")
    import psutil
    from src.core.process_monitor import _belongs_to_current_user_session

    result = []
    for process in psutil.process_iter(["name"]):
        if str(process.info.get("name") or "").casefold() != "spotify.exe":
            continue
        try:
            if not _belongs_to_current_user_session(process):
                continue
            created = process.create_time()
            path = process.exe()
            if _spotify_executable(path, appdata=appdata, local_appdata=local_appdata) and process.create_time() == created:
                result.append(SpotifyProcess(process.pid, created, path))
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise OSError("Spotify 실행 상태를 확인할 권한이 없습니다.") from error
        except OSError:
            if not process.is_running():
                continue  # 조회 중 종료가 확인된 프로세스만 제외한다. 살아 있는 조회 오류는 유지한다.
            raise
    return tuple(result)


def launch_spotify(*, dj: bool = False) -> bool:
    """고정된 Spotify URI를 비활성 최소화로 한 번 요청한다.

    show_cmd는 Spotify에 전달하는 표시 힌트이며 완전 무창·DJ 재생의
    성공을 의미하지 않는다. 실행 수락 뒤 세션을 기다리는 것은 runtime 책임이다.
    """
    if sys.platform != "win32":
        raise OSError("Spotify launch requires a Windows user session")
    os.startfile(SPOTIFY_DJ_URI if dj else "spotify:", show_cmd=7)  # SW_SHOWMINNOACTIVE
    return True


def _current_window(window: SpotifyWindow) -> bool:
    import win32gui
    import win32process
    from src.utils.audio_control import verify_identity
    return (verify_identity(window.process) and win32gui.IsWindow(window.hwnd)
            and win32process.GetWindowThreadProcessId(window.hwnd)[1] == window.process.pid
            and win32gui.IsWindowVisible(window.hwnd) and not win32gui.GetWindow(window.hwnd, 4))


def spotify_window(started_after: float, *, expected: SpotifyWindow | None = None) -> SpotifyWindow | None:
    """cold 요청의 첫 표시 창을 읽고, 이후에는 핀한 그 창만 재확인한다."""
    if sys.platform != "win32":
        raise OSError("Spotify window observation requires Windows")
    if expected is not None:
        return expected if _current_window(expected) else None
    processes = {process.pid: process for process in spotify_processes()
                 if process.create_time >= started_after}
    if not processes:
        return None
    import win32gui
    import win32process

    candidates = []
    def collect(hwnd, _unused):
        if (not win32gui.IsWindowVisible(hwnd)
                or win32gui.GetWindow(hwnd, 4)):  # GW_OWNER: 대화상자·팝업은 제외한다.
            return
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        if pid in processes:
            candidates.append(SpotifyWindow(processes[pid], int(hwnd)))
    win32gui.EnumWindows(collect, None)
    if not candidates:
        return None
    return candidates[0] if _current_window(candidates[0]) else None


def close_spotify_window(window: SpotifyWindow, *, is_current: Callable[[], bool]) -> bool:
    """검증한 창에 WM_CLOSE 한 번을 요청한다. 실제 트레이·재생 유지는 별도 관측이다."""
    if sys.platform != "win32":
        raise OSError("Spotify window close requires Windows")
    if not is_current() or not _current_window(window) or not is_current():
        return False
    import win32gui
    win32gui.PostMessage(window.hwnd, 0x0010, 0, 0)
    return True
