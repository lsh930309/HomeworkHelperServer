# 표준 라이브러리 import
import sys
import datetime
import json
import os
import functools
import ctypes
import subprocess
import atexit
import signal
import time
import tempfile
import glob
import shutil
import threading
from typing import List, Optional, Dict, Any

from src.utils.app_paths import (
    get_app_data_dir,
    get_server_mutex_name,
    get_testbench_session_id,
    is_testbench_mode,
)

# =============================================================================
# [핵심 해결책] OS DPI 무시 + 사용자 지정 배율 적용
# 절전 모드 복구 시 Qt가 배율을 착각하는 문제를 원천 차단
# =============================================================================

def get_user_scale_factor() -> float:
    """QSettings에서 사용자 지정 배율을 읽어옵니다.
    
    Returns:
        float: 배율 (예: 1.0, 1.25, 1.5, 1.75, 2.0)
    """
    try:
        # QSettings를 직접 사용하지 않고 ini 파일 직접 읽기
        # (QApplication 생성 전이므로 QSettings 사용 불가)
        import configparser
        
        config_path = os.path.join(get_app_data_dir(), 'display_settings.ini')
        
        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            config.read(config_path, encoding='utf-8')
            scale_percent = config.getint('Display', 'scale_percent', fallback=100)
            return scale_percent / 100.0
    except Exception as e:
        print(f"[DPI] 사용자 배율 설정 읽기 실패: {e}")
    
    return 1.0  # 기본값 100%

# OS의 High DPI 스케일링 비활성화 (무시)
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

# 사용자 지정 배율 적용
_user_scale = get_user_scale_factor()
os.environ["QT_SCALE_FACTOR"] = str(_user_scale)

# 폰트 DPI 고정 (표준 96 DPI)
os.environ["QT_FONT_DPI"] = "96"

print(f"[DPI] OS DPI 무시, 사용자 배율 적용: {_user_scale * 100:.0f}%")
# =============================================================================

api_server_process = None
_restart_in_progress = False  # 권한 변경으로 인한 재시작 시 True로 설정

# 새로 분리된 모듈 imports
from src.utils.admin import check_admin_requirement, is_admin
from src.gui.main_window import MainWindow
from src.core.instance_manager import run_with_single_instance_check, SingleInstanceApplication
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFontDatabase, QFont
from src.utils.common import get_bundle_resource_path
from src.api.client import ApiClient
from src.api.runtime_config import gui_health_url, resolve_api_port, resolve_local_api_base_url

# Windows 전용 모듈 임포트 (선택적)
if os.name == 'nt':
    try:
        import win32api
        import win32security
        WINDOWS_SECURITY_AVAILABLE = True
    except ImportError:
        WINDOWS_SECURITY_AVAILABLE = False
else:
    WINDOWS_SECURITY_AVAILABLE = False

def cleanup_old_mei_folders():
    """
    이전에 생성되었지만 삭제되지 않은 _MEIxxxxxx 폴더들을 정리합니다.
    현재 프로세스가 사용 중인 폴더는 제외합니다.
    """
    try:
        temp_dir = tempfile.gettempdir()
        # PyInstaller가 생성하는 임시 폴더 이름 패턴
        mei_pattern = os.path.join(temp_dir, '_MEI*')

        # 현재 프로세스가 사용하는 _MEIPASS가 있다면 가져옵니다.
        current_mei_folder = getattr(sys, '_MEIPASS', None)

        cleaned_count = 0
        for folder in glob.glob(mei_pattern):
            if os.path.isdir(folder):
                # 현재 사용 중인 폴더는 건너뜁니다.
                if folder == current_mei_folder:
                    continue

                try:
                    shutil.rmtree(folder, ignore_errors=False)
                    print(f"✓ 이전 임시 폴더 삭제 성공: {folder}")
                    cleaned_count += 1
                except Exception as e:
                    print(f"  이전 임시 폴더 삭제 실패 (사용 중일 수 있음): {folder} - {e}")

        if cleaned_count > 0:
            print(f"총 {cleaned_count}개의 이전 MEI 임시 폴더를 정리했습니다.")
        else:
            print("정리할 이전 MEI 임시 폴더가 없습니다.")
    except Exception as e:
        print(f"임시 폴더 정리 중 오류 발생: {e}")

def _server_health_payload(base_url: str | None = None, timeout: float = 0.5) -> dict[str, Any] | None:
    """Return the local API health payload when a compatible server responds."""
    import requests

    try:
        response = requests.get(gui_health_url(base_url), timeout=timeout)
        if response.status_code != 200:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _is_existing_server_healthy(base_url: str | None = None) -> bool:
    payload = _server_health_payload(base_url=base_url, timeout=0.7)
    return bool(payload and payload.get("ok") is True and payload.get("db_ready") is True)


def wait_for_server_ready(max_wait_seconds: int = 10, base_url: str | None = None) -> bool:
    """서버가 준비될 때까지 대기합니다."""
    print("API 서버 준비 대기 중...")
    import requests
    base_url = resolve_local_api_base_url(base_url)
    iterations = int(max_wait_seconds / 0.2)

    for i in range(iterations):
        try:
            response = requests.get(gui_health_url(base_url), timeout=0.5)
            if response.status_code == 200 and response.json().get("ok") is True:
                print(f"API 서버 준비 완료. ({i * 0.2:.1f}초 소요)")
                return True
        except requests.ConnectionError:
            time.sleep(0.2)
        except ValueError as e:
            print(f"API 서버 health 응답 파싱 오류: {e}")
            time.sleep(0.2)
        except Exception as e:
            print(f"API 서버 확인 중 오류: {e}")
            time.sleep(0.2)

    print("API 서버가 시간 내에 응답하지 않았습니다.")
    return False

def is_server_running() -> bool:
    """
    Windows Named Mutex를 사용하여 서버가 실행 중인지 확인합니다.
    PID 파일보다 훨씬 안정적입니다 (OS 수준에서 자동 관리).
    """
    if os.name != 'nt':
        # Windows 아닌 경우 PID 파일 fallback
        return is_server_running_pid_fallback()

    try:
        import win32event
        import win32api
        import winerror

        mutex_name = get_server_mutex_name()

        # 뮤텍스 열기 시도 (이미 존재하면 서버 실행 중)
        try:
            mutex_handle = win32event.OpenMutex(win32api.GENERIC_READ, False, mutex_name)
            win32api.CloseHandle(mutex_handle)
            return True  # 뮤텍스 존재 = 서버 실행 중
        except Exception as e:
            if getattr(e, 'winerror', None) == winerror.ERROR_FILE_NOT_FOUND:
                return False  # 뮤텍스 없음 = 서버 미실행
            else:
                # 다른 오류 발생 시 PID 파일로 fallback
                print(f"Mutex 확인 오류: {e}, PID 파일로 fallback")
                return is_server_running_pid_fallback()
    except ImportError:
        # pywin32 없으면 PID 파일 fallback
        print("pywin32 없음, PID 파일로 fallback")
        return is_server_running_pid_fallback()

def is_server_running_pid_fallback() -> bool:
    """PID 파일을 확인하여 서버가 실행 중인지 확인 (Fallback 방법)"""
    data_dir = os.path.join(get_app_data_dir(), "homework_helper_data")
    pid_file = os.path.join(data_dir, "db_server.pid")

    if not os.path.exists(pid_file):
        return False

    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())

        # PID가 실제로 실행 중인지 확인
        import psutil
        if psutil.pid_exists(pid):
            try:
                proc = psutil.Process(pid)
                # 프로세스가 존재하고 좀비가 아닌지 확인
                return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False
        return False
    except (ValueError, IOError):
        return False


def _server_pid_file_path() -> str:
    data_dir = os.path.join(get_app_data_dir(), "homework_helper_data")
    return os.path.join(data_dir, "db_server.pid")


def _server_metadata_file_path() -> str:
    data_dir = os.path.join(get_app_data_dir(), "homework_helper_data")
    return os.path.join(data_dir, "db_server_meta.json")


def _read_server_metadata_file() -> dict[str, Any] | None:
    try:
        with open(_server_metadata_file_path(), "r", encoding="utf-8") as f:
            metadata = json.load(f)
        return metadata if isinstance(metadata, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _process_create_time(process_id: int | None) -> float | None:
    if not process_id:
        return None
    try:
        import psutil

        return float(psutil.Process(int(process_id)).create_time())
    except Exception:
        return None


def _process_matches_create_time(process_id: int, expected_create_time: Any) -> bool:
    actual_create_time = _process_create_time(process_id)
    if actual_create_time is None:
        return False
    try:
        expected = float(expected_create_time)
    except (TypeError, ValueError):
        return True
    return abs(actual_create_time - expected) <= 0.001


def _is_existing_api_server_reusable() -> bool:
    """Do not reuse a healthy but orphaned API child from a previous GUI."""

    metadata = _read_server_metadata_file()
    if not metadata:
        return True

    parent_pid = metadata.get("parent_pid")
    if not parent_pid:
        return True

    try:
        parent_pid = int(parent_pid)
    except (TypeError, ValueError):
        return True

    if parent_pid == os.getpid():
        return True

    if not _process_matches_create_time(parent_pid, metadata.get("parent_create_time")):
        print(
            f"기존 API 서버 parent_pid {parent_pid}가 사라졌거나 재사용된 PID입니다. "
            "orphan 서버를 재사용하지 않고 재시작합니다."
        )
        return False
    return True


def _read_server_pid_file() -> int | None:
    try:
        with open(_server_pid_file_path(), "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _process_looks_like_homework_helper(proc: Any) -> bool:
    try:
        name = (proc.name() or "").lower()
    except Exception:
        name = ""
    try:
        command_line = " ".join(proc.cmdline()).lower()
    except Exception:
        command_line = ""
    return (
        "homework_helper" in name
        or "hh_testbench" in name
        or "homeworkhelper" in command_line
        or "homework_helper" in command_line
        or "hh_testbench" in command_line
    )


def _process_looks_like_homework_api_server(
    proc: Any,
    api_listener_pids: set[int] | None = None,
) -> bool:
    if not _process_looks_like_homework_helper(proc):
        return False

    try:
        process_id = int(proc.pid)
    except Exception:
        process_id = None
    if process_id is not None and api_listener_pids and process_id in api_listener_pids:
        return True

    try:
        command_line = " ".join(proc.cmdline()).lower()
    except Exception:
        command_line = ""
    return "--multiprocessing-fork" in command_line or "run_server_main" in command_line


def _find_api_listener_pids(port: int | None = None) -> set[int]:
    try:
        import psutil
    except Exception as exc:
        print(f"API 포트 리스너 확인 실패(psutil 사용 불가): {exc}")
        return set()

    target_port = port or resolve_api_port()
    pids: set[int] = set()
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status != psutil.CONN_LISTEN or not conn.laddr or not conn.pid:
                continue
            try:
                local_port = conn.laddr.port
            except AttributeError:
                local_port = conn.laddr[1]
            if local_port == target_port:
                pids.add(int(conn.pid))
    except Exception as exc:
        print(f"API 포트 리스너 확인 중 오류: {exc}")
    return pids


def _terminate_process_id(
    process_id: int,
    timeout: float = 5.0,
    api_listener_pids: set[int] | None = None,
) -> bool:
    """Terminate a stale HomeworkHelper API process and escalate only if needed."""
    if process_id == os.getpid():
        print(f"현재 프로세스 PID {process_id}는 종료 대상에서 제외합니다.")
        return False

    try:
        import psutil
    except Exception as exc:
        print(f"psutil 사용 불가로 PID {process_id} 종료를 건너뜁니다: {exc}")
        return False

    try:
        proc = psutil.Process(process_id)
    except psutil.NoSuchProcess:
        return True
    except psutil.Error as exc:
        print(f"PID {process_id} 조회 실패: {exc}")
        return False

    if not _process_looks_like_homework_api_server(proc, api_listener_pids=api_listener_pids):
        print(f"PID {process_id}는 HomeworkHelper API 서버로 확인되지 않아 종료하지 않습니다.")
        return False

    try:
        print(f"기존 API 서버 PID {process_id} 종료 요청...")
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except psutil.TimeoutExpired:
            print(f"PID {process_id}가 {timeout:.1f}초 내 종료되지 않아 강제 종료합니다.")
            proc.kill()
            proc.wait(timeout=timeout)
        print(f"기존 API 서버 PID {process_id} 종료 확인.")
        return True
    except psutil.NoSuchProcess:
        return True
    except psutil.Error as exc:
        print(f"PID {process_id} 종료 실패: {exc}")
        return False


def _terminate_existing_api_server(timeout: float = 5.0) -> None:
    """Stop stale API server processes before starting a fresh server."""
    global api_server_process

    known_pids: set[int] = set()
    pid_file_pid = _read_server_pid_file()
    if pid_file_pid:
        known_pids.add(pid_file_pid)
    api_listener_pids = _find_api_listener_pids(resolve_api_port())
    known_pids.update(api_listener_pids)

    if api_server_process and api_server_process.is_alive():
        print(f"현재 GUI가 시작한 API 서버 PID {api_server_process.pid} 종료 요청...")
        api_server_process.terminate()
        api_server_process.join(timeout=timeout)
        if api_server_process.is_alive():
            print(f"API 서버 PID {api_server_process.pid}가 종료되지 않아 강제 종료합니다.")
            api_server_process.kill()
            api_server_process.join(timeout=timeout)
        if api_server_process.pid and not api_server_process.is_alive():
            known_pids.discard(api_server_process.pid)

    for process_id in sorted(known_pids):
        _terminate_process_id(
            process_id,
            timeout=timeout,
            api_listener_pids=api_listener_pids,
        )

    try:
        os.remove(_server_pid_file_path())
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"stale PID 파일 삭제 실패: {exc}")


def _multiprocessing_parent_pid() -> int | None:
    try:
        import multiprocessing

        parent = multiprocessing.parent_process()
        if parent is not None and parent.pid:
            return int(parent.pid)
    except Exception:
        return None
    return None


def _wants_server_only_mode(argv: list[str] | None = None) -> bool:
    """Return True when this process should start only the FastAPI server."""
    args = (argv or sys.argv)[1:]
    return any(arg in {"--server", "--testbench-server", "--run-server"} for arg in args)


def _is_loopback_api_host(host: str | None) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


def _desired_child_api_bind_host() -> tuple[str | None, str]:
    """Return the bind host that the GUI parent should pass to the API child."""
    explicit_host = os.environ.get("HH_API_HOST")
    remote_server_mode_enabled = False
    try:
        from src.data import crud
        from src.data.database import SessionLocal

        db = SessionLocal()
        try:
            settings = crud.get_settings(db)
            remote_server_mode_enabled = bool(getattr(settings, "remote_server_mode_enabled", False))
        finally:
            db.close()
    except Exception as exc:
        print(f"리모트 서버 모드 설정 확인 실패: {exc}")

    if remote_server_mode_enabled and (not explicit_host or _is_loopback_api_host(explicit_host)):
        if explicit_host:
            print(f"리모트 서버 모드가 loopback HH_API_HOST={explicit_host} 설정을 0.0.0.0으로 대체합니다.")
        return "0.0.0.0", "remote_server_mode_enabled"

    if explicit_host:
        return explicit_host, "HH_API_HOST"

    return None, "default_loopback"


def start_api_server() -> bool:
    """FastAPI 서버를 독립 프로세스로 실행합니다 (multiprocessing.Process 방식)."""
    global api_server_process
    try:
        # 이미 서버가 실행 중인지 확인
        if is_server_running():
            if _is_existing_server_healthy() and _is_existing_api_server_reusable():
                print("기존 API 서버가 정상 응답 중입니다. 재사용합니다.")
                return True

            print("기존 API 서버가 응답하지 않거나 현재 GUI에서 재사용할 수 없습니다. 종료 후 재시작합니다...")
            _terminate_existing_api_server(timeout=5.0)

        print("API 서버를 독립 프로세스로 시작합니다...")

        # multiprocessing.Process를 사용하여 서버 프로세스 생성
        # daemon=True: 부모 프로세스(GUI) 종료 시 서버도 자동 종료
        #              SQLite WAL 모드가 DB 무결성 보장
        import multiprocessing
        child_bind_host, child_bind_source = _desired_child_api_bind_host()
        env_had_api_host = "HH_API_HOST" in os.environ
        previous_api_host = os.environ.get("HH_API_HOST")
        if child_bind_host:
            os.environ["HH_API_HOST"] = child_bind_host
        print(f"API 서버 child 바인딩 요청: {child_bind_host or '127.0.0.1'} ({child_bind_source})")
        try:
            api_server_process = multiprocessing.Process(
                target=run_server_main,
                daemon=True
            )
            api_server_process.start()
        finally:
            if child_bind_host:
                if env_had_api_host:
                    os.environ["HH_API_HOST"] = previous_api_host or ""
                else:
                    os.environ.pop("HH_API_HOST", None)
        print(f"API 서버가 독립 프로세스 PID {api_server_process.pid}로 시작되었습니다.")

        # 서버가 준비될 때까지 대기
        return wait_for_server_ready()

    except Exception as e:
        print(f"API 서버 시작 실패: {e}")
        message = f"API 서버 시작에 실패했습니다.\n\n{e}"
        try:
            app = QApplication.instance()
            if app is not None:
                QMessageBox.critical(None, "치명적 오류", message)
            elif os.name == "nt":
                ctypes.windll.user32.MessageBoxW(0, message, "치명적 오류", 0x10)
            else:
                print(message, file=sys.stderr)
        except Exception as msgbox_exc:
            print(f"[start_api_server] 오류 표시 실패: {msgbox_exc}", file=sys.stderr)
            print(message, file=sys.stderr)
        return False

def run_server_main():
    """uvicorn 서버만 실행하는 함수.

    GUI에서 multiprocessing으로 호출하거나, SSH testbench가 ``--testbench-server``
    / ``--server`` 인자로 직접 실행한다.
    """
    import signal
    import threading
    import logging
    from logging.handlers import RotatingFileHandler
    from sqlalchemy import text

    # multiprocessing 환경에서 stdout/stderr가 None일 수 있으므로 재설정
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')

    # PID 파일 및 로그 파일 경로 설정 (%APPDATA% 사용)
    app_data_dir = get_app_data_dir()
    data_dir = os.path.join(app_data_dir, "homework_helper_data")
    os.makedirs(data_dir, exist_ok=True)
    pid_file = os.path.join(data_dir, "db_server.pid")
    log_file = os.path.join(data_dir, "db_server.log")
    metadata_file = os.path.join(data_dir, "db_server_meta.json")
    parent_process_id = _multiprocessing_parent_pid()
    mutex_name = get_server_mutex_name()

    # 로깅 시스템 설정 (파일 기반, 순환 로그)
    logger = logging.getLogger('DBServer')
    logger.setLevel(logging.INFO)

    # 로그 포맷 설정
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 파일 핸들러 (최대 10MB, 5개 파일 유지)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 콘솔 핸들러 (개발 환경에서 확인용)
    if not getattr(sys, 'frozen', False):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.info("=" * 60)
    logger.info("서버 모드로 실행합니다.")
    logger.info(f"PID: {os.getpid()}")
    logger.info(f"부모 GUI PID: {parent_process_id or 'unknown'}")
    logger.info(f"로그 파일: {log_file}")
    logger.info(f"데이터 디렉토리: {data_dir}")
    logger.info(f"테스트벤치 모드: {is_testbench_mode()}")

    # Windows Named Mutex 생성 (프로세스 유일성 보장)
    server_mutex = None
    if os.name == 'nt':
        try:
            import win32event
            import win32api
            server_mutex = win32event.CreateMutex(None, False, mutex_name)
            if win32api.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                logger.error("서버가 이미 실행 중입니다! 중복 실행 불가.")
                sys.exit(1)
            logger.info(f"Windows Named Mutex 생성 완료: {mutex_name}")
        except ImportError:
            logger.warning("pywin32 없음: Named Mutex 사용 불가, PID 파일만 사용")
        except Exception as e:
            logger.error(f"Mutex 생성 실패: {e}")

    # PID 파일 생성 (Mutex와 함께 사용, fallback 용도)
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"PID 파일 생성: {pid_file}")
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "pid": os.getpid(),
                    "parent_pid": parent_process_id,
                    "parent_create_time": _process_create_time(parent_process_id),
                    "started_at": time.time(),
                    "started_at_iso": datetime.datetime.now().isoformat(),
                    "api_port": resolve_api_port(),
                    "server_mutex_name": mutex_name,
                    "testbench_mode": is_testbench_mode(),
                    "testbench_session_id": get_testbench_session_id(),
                    "app_data_dir": app_data_dir,
                    "data_dir": data_dir,
                    "executable": sys.executable,
                    "argv": sys.argv,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        logger.info(f"서버 메타데이터 파일 생성: {metadata_file}")
    except Exception as e:
        logger.error(f"PID/메타데이터 파일 생성 실패: {e}")

    # --- main.py의 내용을 여기로 통합 ---
    from fastapi import FastAPI, Depends, HTTPException, Header
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel
    from sqlalchemy.orm import Session
    from src.data import crud, models, schemas, beholder
    from src.data.database import SessionLocal, engine, auto_migrate_database, backup_database

    # DB 백업 (마이그레이션 전, 이전 세션의 최종 상태 보존)
    backup_database()

    # 자동 마이그레이션 실행 (새 컬럼 추가)
    auto_migrate_database()

    # 테이블 생성 (새 DB인 경우)
    models.Base.metadata.create_all(bind=engine)

    # 데이터베이스 무결성 확인 및 복구
    logger.info("데이터베이스 무결성 확인 중...")
    try:
        with engine.connect() as conn:
            # WAL 복구 체크포인트
            conn.execute(text("PRAGMA wal_checkpoint(RECOVER)"))
            conn.commit()

            # 무결성 검사
            result = conn.execute(text("PRAGMA integrity_check"))
            integrity_result = result.scalar()
            if integrity_result != "ok":
                logger.warning(f"데이터베이스 무결성 검사 실패: {integrity_result}")
            else:
                logger.info("데이터베이스 무결성 확인 완료.")
    except Exception as e:
        logger.error(f"데이터베이스 복구 중 오류: {e}", exc_info=True)

    # 데이터베이스 테이블 생성
    # 기존 데이터 호환을 위해 필요한 컬럼이 없으면 추가
    try:
        ensure_process_table_schema()
    except Exception as e:
        logger.error(f"테이블 스키마 보정 실패: {e}", exc_info=True)

    def resolve_api_bind_host() -> str:
        explicit_host = os.environ.get("HH_API_HOST")
        if explicit_host:
            logger.info(f"API 바인딩 설정 확인: HH_API_HOST={explicit_host}")
            return explicit_host
        db = SessionLocal()
        try:
            settings = crud.get_settings(db)
            remote_server_mode_enabled = bool(getattr(settings, "remote_server_mode_enabled", False))
            logger.info(f"API 바인딩 설정 확인: remote_server_mode_enabled={remote_server_mode_enabled}")
            if remote_server_mode_enabled:
                return "0.0.0.0"
        except Exception as e:
            logger.error(f"리모트 서버 모드 설정 확인 실패: {e}", exc_info=True)
        finally:
            db.close()
        return "127.0.0.1"

    # 주기적 WAL checkpoint 백그라운드 스레드
    def periodic_checkpoint(interval=60):
        """주기적으로 WAL checkpoint 수행"""
        while True:
            try:
                time.sleep(interval)
                from src.api.beholder_routes import database_access_gate
                with database_access_gate():
                    with engine.connect() as conn:
                        conn.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
                        conn.commit()
                logger.info("WAL checkpoint 완료")
            except Exception as e:
                logger.error(f"Checkpoint 오류: {e}", exc_info=True)

    checkpoint_thread = threading.Thread(target=periodic_checkpoint, args=(60,), daemon=True)
    checkpoint_thread.start()
    logger.info("주기적 WAL checkpoint 스레드 시작 (60초 간격)")

    # Graceful shutdown 핸들러
    shutdown_lock = threading.Lock()
    shutdown_state = {"started": False}

    def shutdown_api_resources(reason: str, signum: int | None = None) -> None:
        """Flush DB state and remove lifecycle files exactly once."""
        with shutdown_lock:
            if shutdown_state["started"]:
                return
            shutdown_state["started"] = True

        logger.info(f"서버 종료 절차 시작: {reason} (Signal: {signum})")

        try:
            logger.info("최종 WAL checkpoint 수행 중...")
            with engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                conn.commit()
            logger.info("WAL checkpoint 완료")
        except Exception as e:
            logger.error(f"최종 WAL checkpoint 실패: {e}", exc_info=True)

        try:
            engine.dispose()
            logger.info("데이터베이스 연결 종료")
        except Exception as e:
            logger.error(f"데이터베이스 연결 종료 실패: {e}", exc_info=True)

        if server_mutex and os.name == 'nt':
            try:
                import win32api
                win32api.CloseHandle(server_mutex)
                logger.info("Windows Named Mutex 해제")
            except Exception as e:
                logger.warning(f"Windows Named Mutex 해제 실패: {e}")

        for lifecycle_file, label in ((pid_file, "PID"), (metadata_file, "메타데이터")):
            try:
                if os.path.exists(lifecycle_file):
                    os.remove(lifecycle_file)
                    logger.info(f"{label} 파일 삭제: {lifecycle_file}")
            except Exception as e:
                logger.error(f"{label} 파일 삭제 실패: {e}", exc_info=True)

        logger.info("서버 종료 완료")
        logger.info("=" * 60)

    def shutdown_handler(signum, frame):
        """종료 신호 처리 - 안전하게 종료"""
        shutdown_api_resources("signal", signum=signum)
        sys.exit(0)

    def start_parent_watchdog(parent_pid: int | None) -> None:
        if not parent_pid:
            logger.info("부모 GUI PID를 확인할 수 없어 parent watchdog을 비활성화합니다.")
            return

        try:
            import psutil
            parent_create_time = psutil.Process(parent_pid).create_time()
        except Exception as e:
            parent_create_time = None
            logger.warning(f"부모 GUI PID {parent_pid} 생성시각 확인 실패: {e}")

        def watch_parent() -> None:
            try:
                import psutil
                while True:
                    time.sleep(5)
                    try:
                        parent = psutil.Process(parent_pid)
                        if parent_create_time is not None and abs(parent.create_time() - parent_create_time) > 0.001:
                            raise psutil.NoSuchProcess(parent_pid)
                    except psutil.NoSuchProcess:
                        logger.warning(
                            "부모 GUI PID %s가 사라졌습니다. stale API 서버 방지를 위해 종료합니다.",
                            parent_pid,
                        )
                        shutdown_api_resources(f"parent_pid_{parent_pid}_gone")
                        os._exit(0)
                    except Exception as e:
                        logger.warning(f"부모 GUI PID {parent_pid} 확인 실패: {e}")
            except Exception as e:
                logger.error(f"parent watchdog 치명 오류: {e}", exc_info=True)

        watchdog_thread = threading.Thread(
            target=watch_parent,
            name="api-parent-watchdog",
            daemon=True,
        )
        watchdog_thread.start()
        logger.info(f"parent watchdog 시작: parent_pid={parent_pid}")

    # Windows에서 Ctrl+C 처리
    if os.name == 'nt':
        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)
        signal.signal(signal.SIGBREAK, shutdown_handler)
        logger.info("종료 신호 핸들러 등록 완료 (SIGINT, SIGTERM, SIGBREAK)")

    start_parent_watchdog(parent_process_id)

    api_host = resolve_api_bind_host()
    api_port = resolve_api_port()
    try:
        if os.path.exists(metadata_file):
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        else:
            metadata = {}
        metadata["api_host"] = api_host
        metadata["api_port"] = api_port
        metadata["remote_exposed"] = api_host not in {"127.0.0.1", "localhost", "::1"}
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"API 바인딩 메타데이터 갱신 실패: {e}")

    app = FastAPI()
    loopback_hosts = {"127.0.0.1", "localhost", "::1", "testclient"}
    remote_exposed = api_host not in {"127.0.0.1", "localhost", "::1"}

    def _request_from_loopback(request) -> bool:
        return bool(request.client and request.client.host in loopback_hosts)

    def _is_remote_public_icon_request(path: str, method: str) -> bool:
        return method in {"GET", "HEAD"} and (
            path.startswith("/api/dashboard/icons/")
            or path.startswith("/api/dashboard/resource-icons/")
        )

    @app.middleware("http")
    async def remote_exposure_boundary_middleware(request, call_next):
        """Expose only /remote/* to non-loopback peers when the API binds externally."""

        if remote_exposed and not _request_from_loopback(request):
            path = request.url.path
            if (
                path != "/remote"
                and not path.startswith("/remote/")
                and not _is_remote_public_icon_request(path, request.method.upper())
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Remote server mode exposes only the authenticated /remote API to non-loopback clients."},
                )
        return await call_next(request)

    @app.middleware("http")
    async def remote_diagnostics_middleware(request, call_next):
        """Log slow local GUI/Remote Agent requests without touching secrets."""
        path = request.url.path
        should_trace = path.startswith("/api/gui/") or path.startswith("/remote/")
        if not should_trace:
            return await call_next(request)

        started_at = time.perf_counter()
        status_code: int | str = "error"
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started_at) * 1000
            if duration_ms >= 1000:
                logger.warning(
                    "slow_api_request method=%s path=%s status=%s duration_ms=%.1f pid=%s thread=%s",
                    request.method,
                    path,
                    status_code,
                    duration_ms,
                    os.getpid(),
                    threading.get_ident(),
                )

    class ProcessRuntimeStatePatch(BaseModel):
        last_played_timestamp: float | None = None
        stamina_current: int | None = None
        stamina_max: int | None = None
        stamina_updated_at: float | None = None
        resource_percent: float | None = None
        resource_updated_at: float | None = None
        resource_status: str | None = None
        resource_label: str | None = None

    class ProcessStaminaPatch(BaseModel):
        stamina_current: int
        stamina_max: int
        stamina_updated_at: float

    class ProcessResourcePatch(BaseModel):
        resource_percent: float | None = None
        resource_updated_at: float | None = None
        resource_status: str | None = None
        resource_label: str | None = None

    @app.exception_handler(beholder.BeholderBlocked)
    async def beholder_blocked_handler(request, exc):
        return JSONResponse(
            status_code=409,
            content={
                "detail": exc.incident.safe_recommendation or "Beholder가 비정상 데이터 변경을 차단했습니다.",
                "beholder_incident": beholder.incident_to_dict(exc.incident),
            },
        )

    # Dependency
    def get_db():
        from src.api.beholder_routes import database_access_gate
        with database_access_gate():
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()

    def _dashboard_static_health() -> dict[str, Any]:
        from src.api.dashboard.static_files import dashboard_static_dir

        static_path = dashboard_static_dir()
        ready = (
            static_path.exists()
            and (static_path / "dashboard.js").exists()
            and (static_path / "dashboard.css").exists()
        )
        return {"ready": ready, "path": str(static_path)}

    @app.get("/api/gui/ping")
    async def gui_ping():
        return {
            "ok": True,
            "pid": os.getpid(),
            "host": api_host,
            "port": api_port,
            "testbench_mode": is_testbench_mode(),
            "testbench_session_id": get_testbench_session_id(),
            "server_time": time.time(),
        }

    @app.get("/api/gui/health")
    def gui_health():
        started_at = time.perf_counter()
        db_ready = False
        db_error: str | None = None
        db_started_at = time.perf_counter()
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ready = True
        except Exception as e:
            db_error = str(e)
        db_probe_ms = (time.perf_counter() - db_started_at) * 1000

        static_started_at = time.perf_counter()
        dashboard_static = _dashboard_static_health()
        static_probe_ms = (time.perf_counter() - static_started_at) * 1000
        return {
            "ok": db_ready,
            "pid": os.getpid(),
            "host": api_host,
            "port": api_port,
            "base_url": f"http://127.0.0.1:{api_port}",
            "bind_host": api_host,
            "remote_exposed": remote_exposed,
            "testbench_mode": is_testbench_mode(),
            "testbench_session_id": get_testbench_session_id(),
            "db_ready": db_ready,
            "db_error": db_error,
            "db_probe_ms": round(db_probe_ms, 2),
            "dashboard_static_ready": dashboard_static["ready"],
            "dashboard_static_path": dashboard_static["path"],
            "static_probe_ms": round(static_probe_ms, 2),
            "total_ms": round((time.perf_counter() - started_at) * 1000, 2),
        }

    # create / read / update / delete [managed processes]
    @app.get("/processes", response_model=List[schemas.ProcessSchema])
    def get_all_processes(db: Session = Depends(get_db)):
        processes = crud.get_processes(db)
        return processes

    @app.get("/processes/{process_id}", response_model=schemas.ProcessSchema)
    def get_process_by_id(process_id: str, db: Session = Depends(get_db)):
        db_process = crud.get_process_by_id(db=db, process_id=process_id)
        if db_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return db_process

    @app.post("/processes", response_model=schemas.ProcessSchema, status_code=201)
    def create_new_process(
        process_data: schemas.ProcessCreateSchema,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        return crud.create_process(
            db=db,
            process=process_data,
            actor=x_hh_beholder_actor or "process_editor",
            operation_kind=x_hh_beholder_operation or "process_create",
            override_token=x_hh_beholder_override,
        )

    @app.put("/processes/{process_id}", response_model=schemas.ProcessSchema)
    def update_existing_process(
        process_id: str,
        process_data: schemas.ProcessCreateSchema,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        updated_process = crud.update_process(
            db=db,
            process_id=process_id,
            process=process_data,
            actor=x_hh_beholder_actor or "process_editor",
            operation_kind=x_hh_beholder_operation or "process_update",
            override_token=x_hh_beholder_override,
        )
        if updated_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return updated_process

    @app.patch("/processes/{process_id}/runtime-state", response_model=schemas.ProcessSchema)
    def update_process_runtime_state(
        process_id: str,
        patch: ProcessRuntimeStatePatch,
        db: Session = Depends(get_db),
        x_hh_beholder_override: str | None = Header(None),
    ):
        updated_process = crud.update_process_runtime_state(
            db=db,
            process_id=process_id,
            last_played_timestamp=patch.last_played_timestamp,
            stamina_current=patch.stamina_current,
            stamina_max=patch.stamina_max,
            stamina_updated_at=patch.stamina_updated_at,
            resource_percent=patch.resource_percent,
            resource_updated_at=patch.resource_updated_at,
            resource_status=patch.resource_status,
            resource_label=patch.resource_label,
            actor="process_monitor",
            operation_kind="process_runtime_state_update",
            override_token=x_hh_beholder_override,
        )
        if updated_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return updated_process

    @app.patch("/processes/{process_id}/stamina", response_model=schemas.ProcessSchema)
    def update_process_stamina(
        process_id: str,
        patch: ProcessStaminaPatch,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        updated_process = crud.update_process_stamina(
            db=db,
            process_id=process_id,
            stamina_current=patch.stamina_current,
            stamina_max=patch.stamina_max,
            stamina_updated_at=patch.stamina_updated_at,
            actor=x_hh_beholder_actor or "hoyolab_slow_followup",
            operation_kind=x_hh_beholder_operation or "process_stamina_refresh",
            override_token=x_hh_beholder_override,
        )
        if updated_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return updated_process

    @app.patch("/processes/{process_id}/resource", response_model=schemas.ProcessSchema)
    def update_process_resource(
        process_id: str,
        patch: ProcessResourcePatch,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        updated_process = crud.update_process_resource(
            db=db,
            process_id=process_id,
            resource_percent=patch.resource_percent,
            resource_updated_at=patch.resource_updated_at,
            resource_status=patch.resource_status,
            resource_label=patch.resource_label,
            actor=x_hh_beholder_actor or "resource_tracker",
            operation_kind=x_hh_beholder_operation or "process_resource_update",
            override_token=x_hh_beholder_override,
        )
        if updated_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return updated_process

    @app.delete("/processes/{process_id}")
    def delete_existing_process(
        process_id: str,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        deleted_process = crud.delete_process(
            db=db,
            process_id=process_id,
            actor=x_hh_beholder_actor or "process_editor",
            operation_kind=x_hh_beholder_operation or "process_delete",
            override_token=x_hh_beholder_override,
        )
        if deleted_process is None:
            raise HTTPException(status_code=404, detail="프로세스를 찾을 수 없습니다.")
        return {"message": "프로세스가 삭제되었습니다."}

    # create / read / update / delete [web shortcuts]
    @app.get("/shortcuts", response_model=List[schemas.WebShortcutSchema])
    def get_all_shortcuts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        shortcuts = crud.get_shortcuts(db, skip=skip, limit=limit)
        return shortcuts

    @app.get("/shortcuts/{shortcut_id}", response_model=schemas.WebShortcutSchema)
    def get_shortcut_by_id(shortcut_id: str, db: Session = Depends(get_db)):
        db_shortcut = crud.get_shortcut_by_id(db, shortcut_id)
        if db_shortcut is None:
            raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
        return db_shortcut

    @app.post("/shortcuts", response_model=schemas.WebShortcutSchema, status_code=201)
    def create_new_shortcut(
        shortcut_data: schemas.WebShortcutCreate,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        return crud.create_shortcut(
            db=db,
            shortcut=shortcut_data,
            actor=x_hh_beholder_actor or "web_shortcut_editor",
            operation_kind=x_hh_beholder_operation or "shortcut_create",
            override_token=x_hh_beholder_override,
        )

    @app.put("/shortcuts/{shortcut_id}", response_model=schemas.WebShortcutSchema)
    def update_existing_shortcut(
        shortcut_id: str,
        shortcut_data: schemas.WebShortcutCreate,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        updated_shortcut = crud.update_shortcut(
            db=db,
            shortcut_id=shortcut_id,
            shortcut=shortcut_data,
            actor=x_hh_beholder_actor or "web_shortcut_editor",
            operation_kind=x_hh_beholder_operation or "shortcut_update",
            override_token=x_hh_beholder_override,
        )
        if updated_shortcut is None:
            raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
        return updated_shortcut

    @app.post("/shortcuts/{shortcut_id}/opened", response_model=schemas.WebShortcutSchema)
    def mark_shortcut_opened(
        shortcut_id: str,
        db: Session = Depends(get_db),
        x_hh_beholder_override: str | None = Header(None),
    ):
        updated_shortcut = crud.mark_shortcut_opened(
            db=db,
            shortcut_id=shortcut_id,
            opened_at=datetime.datetime.now().timestamp(),
            override_token=x_hh_beholder_override,
        )
        if updated_shortcut is None:
            raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
        return updated_shortcut

    @app.delete("/shortcuts/{shortcut_id}")
    def delete_existing_shortcut(
        shortcut_id: str,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        deleted_shortcut = crud.delete_shortcut(
            db=db,
            shortcut_id=shortcut_id,
            actor=x_hh_beholder_actor or "web_shortcut_editor",
            operation_kind=x_hh_beholder_operation or "shortcut_delete",
            override_token=x_hh_beholder_override,
        )
        if deleted_shortcut is None:
            raise HTTPException(status_code=404, detail="웹 바로 가기를 찾을 수 없습니다.")
        return {"message": "웹 바로 가기가 삭제되었습니다."}

    # read / update [global settings]
    @app.get("/settings", response_model=schemas.GlobalSettingsSchema)
    def get_global_settings(db: Session = Depends(get_db)):
        return crud.get_settings(db)

    @app.put("/settings", response_model=schemas.GlobalSettingsSchema)
    def update_global_settings(
        settings_data: schemas.GlobalSettingsSchema,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        actor = x_hh_beholder_actor or "settings_full_update"
        return crud.update_settings(
            db=db,
            settings=settings_data,
            actor=actor,
            operation_kind=x_hh_beholder_operation or "settings_update",
            allowed_fields=beholder.allowed_settings_fields_for_actor(actor),
            override_token=x_hh_beholder_override,
        )

    @app.patch("/settings", response_model=schemas.GlobalSettingsSchema)
    def patch_global_settings(
        settings_data: dict[str, Any],
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        actor = x_hh_beholder_actor or "settings_patch"
        return crud.patch_settings(
            db=db,
            updates=settings_data,
            actor=actor,
            operation_kind=x_hh_beholder_operation or "settings_update",
            allowed_fields=beholder.allowed_settings_fields_for_actor(actor),
            override_token=x_hh_beholder_override,
        )

    # create / read / update [process sessions]
    @app.post("/sessions", response_model=schemas.ProcessSessionSchema, status_code=201)
    def create_new_session(
        session_data: schemas.ProcessSessionCreate,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        """새로운 프로세스 세션 시작"""
        return crud.create_session(
            db=db,
            session=session_data,
            actor=x_hh_beholder_actor or "process_monitor",
            operation_kind=x_hh_beholder_operation or "runtime_start",
            override_token=x_hh_beholder_override,
        )

    @app.put("/sessions/{session_id}/end", response_model=schemas.ProcessSessionSchema)
    def end_process_session(
        session_id: int,
        end_data: schemas.ProcessSessionUpdate,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        """프로세스 세션 종료"""
        ended_session = crud.end_session(
            db=db,
            session_id=session_id,
            end_timestamp=end_data.end_timestamp,
            stamina_at_end=end_data.stamina_at_end,
            resource_percent_at_end=end_data.resource_percent_at_end,
            actor=x_hh_beholder_actor or "process_monitor",
            operation_kind=x_hh_beholder_operation or "runtime_stop",
            close_reason=end_data.close_reason or "process_exit",
            override_token=x_hh_beholder_override,
        )
        if ended_session is None:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        return ended_session

    @app.get("/sessions/process/{process_id}", response_model=List[schemas.ProcessSessionSchema])
    def get_sessions_by_process(process_id: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        """특정 프로세스의 세션 이력 조회"""
        return crud.get_sessions_by_process_id(db=db, process_id=process_id, skip=skip, limit=limit)

    @app.get("/sessions/process/{process_id}/active", response_model=schemas.ProcessSessionSchema)
    def get_active_session(process_id: str, db: Session = Depends(get_db)):
        """특정 프로세스의 현재 활성 세션 조회"""
        session = crud.get_active_session_by_process_id(db=db, process_id=process_id)
        if session is None:
            raise HTTPException(status_code=404, detail="활성 세션이 없습니다.")
        return session

    @app.get("/sessions/process/{process_id}/last", response_model=schemas.ProcessSessionSchema)
    def get_last_session(process_id: str, db: Session = Depends(get_db)):
        """특정 프로세스의 가장 최근 완료된 세션 조회"""
        session = crud.get_last_session(db=db, process_id=process_id)
        if session is None:
            raise HTTPException(status_code=404, detail="완료된 세션이 없습니다.")
        return session

    @app.patch("/sessions/{session_id}/stamina", response_model=schemas.ProcessSessionSchema)
    def update_session_stamina(
        session_id: int,
        stamina_at_end: int,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        """세션의 종료 스태미나 값을 업데이트"""
        success = crud.update_session_stamina(
            db=db,
            session_id=session_id,
            stamina_at_end=stamina_at_end,
            actor=x_hh_beholder_actor or "hoyolab_slow_followup",
            operation_kind=x_hh_beholder_operation or "hoyolab_session_stamina_rewrite",
            override_token=x_hh_beholder_override,
        )
        if not success:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        # 업데이트된 세션 반환
        session = db.query(models.ProcessSession).filter(models.ProcessSession.id == session_id).first()
        return session

    @app.patch("/sessions/{session_id}/resource", response_model=schemas.ProcessSessionSchema)
    def update_session_resource(
        session_id: int,
        resource_percent_at_end: float,
        db: Session = Depends(get_db),
        x_hh_beholder_actor: str | None = Header(None),
        x_hh_beholder_operation: str | None = Header(None),
        x_hh_beholder_override: str | None = Header(None),
    ):
        """세션의 종료 외부 리소스 백분율을 업데이트"""
        success = crud.update_session_resource(
            db=db,
            session_id=session_id,
            resource_percent_at_end=resource_percent_at_end,
            actor=x_hh_beholder_actor or "resource_slow_followup",
            operation_kind=x_hh_beholder_operation or "resource_session_percent_rewrite",
            override_token=x_hh_beholder_override,
        )
        if not success:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        session = db.query(models.ProcessSession).filter(models.ProcessSession.id == session_id).first()
        return session

    @app.get("/sessions", response_model=List[schemas.ProcessSessionSchema])
    def get_all_sessions_list(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
        """모든 세션 조회"""
        return crud.get_all_sessions(db=db, skip=skip, limit=limit)

    # === 대시보드 라우터 및 정적 파일 등록 ===
    from fastapi.staticfiles import StaticFiles
    from src.api.dashboard import router as dashboard_router
    from src.api.beholder_routes import router as beholder_router
    from src.api.dashboard.static_files import dashboard_static_dir
    from src.api.remote_routes import create_remote_router
    
    # 정적 파일 서빙 (CSS, JS)
    dashboard_static_path = dashboard_static_dir()
    if dashboard_static_path.exists():
        app.mount("/static/dashboard", StaticFiles(directory=str(dashboard_static_path)), name="dashboard_static")
        logger.info(f"정적 파일 서빙 등록: {dashboard_static_path}")
    else:
        logger.warning(f"대시보드 정적 파일 없음: {dashboard_static_path}")
    
    app.include_router(dashboard_router)
    app.include_router(beholder_router)

    remote_require_auth = (
        os.environ.get("HH_REMOTE_REQUIRE_AUTH", "").lower() in {"1", "true", "yes", "on"}
        or api_host not in loopback_hosts
    )
    if remote_require_auth and not os.environ.get("HH_REMOTE_TOKEN"):
        logger.warning(
            "Remote API 인증 강제 모드입니다. 기존 pairing token이 없다면 로컬에서 /remote/pair/start로 먼저 페어링하세요."
        )
    app.include_router(create_remote_router(get_db, require_auth=remote_require_auth))
    logger.info("대시보드 라우터 등록 완료 (/dashboard, /api/dashboard/*)")
    logger.info("리모트 컨트롤 라우터 등록 완료 (/remote/*)")


    import uvicorn
    # uvicorn.run에 문자열 대신 app 객체를 직접 전달합니다.
    logger.info(f"API 서버 바인딩: {api_host}:{api_port}")
    try:
        uvicorn.run(app, host=api_host, port=api_port, log_level="warning")
    finally:
        shutdown_api_resources("uvicorn_returned")

def stop_api_server():
    """독립 프로세스로 실행된 API 서버를 종료합니다."""
    global api_server_process
    if api_server_process and api_server_process.is_alive():
        print(f"API 서버(PID: {api_server_process.pid}) 종료 중...")
        _terminate_existing_api_server(timeout=5.0)
        api_server_process = None
        print("API 서버 종료 완료.")

def ensure_process_table_schema():
    """
    managed_processes 및 global_settings 테이블에 신규 컬럼이 없으면 추가합니다.
    기존 사용자 데이터가 손실되지 않도록 ALTER TABLE을 사용합니다.
    """
    try:
        from sqlalchemy import text
        from src.data.database import engine

        with engine.connect() as conn:
            # === managed_processes 테이블 마이그레이션 ===
            table_exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='managed_processes'")
            ).fetchone()
            if table_exists:
                existing_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(managed_processes)"))}

                if 'preferred_launch_type' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN preferred_launch_type TEXT DEFAULT 'shortcut'"))
                if 'user_preset_id' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN user_preset_id TEXT"))
                # HoYoLab 스태미나 컬럼 추가
                if 'stamina_tracking_enabled' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN stamina_tracking_enabled BOOLEAN DEFAULT 0"))
                if 'hoyolab_game_id' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN hoyolab_game_id TEXT"))
                if 'stamina_current' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN stamina_current INTEGER"))
                if 'stamina_max' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN stamina_max INTEGER"))
                if 'stamina_updated_at' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN stamina_updated_at REAL"))
                if 'resource_tracking_enabled' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN resource_tracking_enabled BOOLEAN DEFAULT 0"))
                    existing_cols.add('resource_tracking_enabled')
                if 'resource_provider' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN resource_provider TEXT"))
                    existing_cols.add('resource_provider')
                if 'resource_key' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN resource_key TEXT"))
                    existing_cols.add('resource_key')
                if 'resource_label' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN resource_label TEXT"))
                    existing_cols.add('resource_label')
                if 'resource_percent' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN resource_percent REAL"))
                    existing_cols.add('resource_percent')
                if 'resource_updated_at' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN resource_updated_at REAL"))
                    existing_cols.add('resource_updated_at')
                if 'resource_status' not in existing_cols:
                    conn.execute(text("ALTER TABLE managed_processes ADD COLUMN resource_status TEXT"))
                    existing_cols.add('resource_status')
                if {'resource_provider', 'resource_key', 'resource_label'}.issubset(existing_cols):
                    conn.execute(text(
                        "UPDATE managed_processes "
                        "SET resource_label = '전초기지 방어 보상' "
                        "WHERE resource_provider = 'nikke_blablalink' "
                        "AND resource_key = 'nikke_outpost_storage' "
                        "AND (resource_label IS NULL OR resource_label = '' OR resource_label = '보관함 용량')"
                    ))

            # === global_settings 테이블 마이그레이션 ===
            gs_table_exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='global_settings'")
            ).fetchone()
            if gs_table_exists:
                gs_existing_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(global_settings)"))}

                # 스태미나 알림 설정 컬럼 추가
                if 'stamina_notify_enabled' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN stamina_notify_enabled INTEGER DEFAULT 1"))
                    print("[Migration] global_settings.stamina_notify_enabled 컬럼 추가됨")
                if 'stamina_notify_threshold' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN stamina_notify_threshold INTEGER DEFAULT 20"))
                    print("[Migration] global_settings.stamina_notify_threshold 컬럼 추가됨")

                # 사이드바 설정 컬럼 추가
                if 'sidebar_enabled' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_enabled INTEGER DEFAULT 1"))
                    print("[Migration] global_settings.sidebar_enabled 컬럼 추가됨")
                sidebar_mode_added = False
                if 'sidebar_mode' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_mode TEXT DEFAULT 'game'"))
                    print("[Migration] global_settings.sidebar_mode 컬럼 추가됨")
                    gs_existing_cols.add('sidebar_mode')
                    sidebar_mode_added = True
                if 'sidebar_mode' in gs_existing_cols and 'sidebar_enabled' in gs_existing_cols:
                    mode_where = (
                        "1 = 1"
                        if sidebar_mode_added
                        else "sidebar_mode IS NULL OR sidebar_mode = '' OR sidebar_mode NOT IN ('always', 'game', 'disabled')"
                    )
                    conn.execute(text(
                        "UPDATE global_settings "
                        "SET sidebar_mode = CASE WHEN COALESCE(sidebar_enabled, 1) = 0 THEN 'disabled' ELSE 'game' END "
                        f"WHERE {mode_where}"
                    ))
                if 'sidebar_auto_hide_sec' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_auto_hide_sec INTEGER DEFAULT 3"))
                    print("[Migration] global_settings.sidebar_auto_hide_sec 컬럼 추가됨")
                if 'sidebar_height_ratio' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_height_ratio REAL DEFAULT 1.0"))
                    print("[Migration] global_settings.sidebar_height_ratio 컬럼 추가됨")
                if 'sidebar_opacity' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_opacity REAL DEFAULT 0.85"))
                    print("[Migration] global_settings.sidebar_opacity 컬럼 추가됨")
                if 'sidebar_clock_enabled' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_clock_enabled INTEGER DEFAULT 1"))
                    print("[Migration] global_settings.sidebar_clock_enabled 컬럼 추가됨")
                if 'sidebar_clock_format' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_clock_format TEXT DEFAULT '%H:%M:%S'"))
                    print("[Migration] global_settings.sidebar_clock_format 컬럼 추가됨")
                if 'sidebar_playtime_enabled' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_playtime_enabled INTEGER DEFAULT 1"))
                    print("[Migration] global_settings.sidebar_playtime_enabled 컬럼 추가됨")
                if 'sidebar_playtime_prefix' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_playtime_prefix TEXT DEFAULT '오늘 플레이 시간'"))
                    print("[Migration] global_settings.sidebar_playtime_prefix 컬럼 추가됨")
                if 'sidebar_volume_section_enabled' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN sidebar_volume_section_enabled INTEGER DEFAULT 1"))
                    print("[Migration] global_settings.sidebar_volume_section_enabled 컬럼 추가됨")
                if 'screenshot_trigger_vk' not in gs_existing_cols:
                    conn.execute(text("ALTER TABLE global_settings ADD COLUMN screenshot_trigger_vk INTEGER DEFAULT 178"))
                    print("[Migration] global_settings.screenshot_trigger_vk 컬럼 추가됨")

            ps_table_exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='process_sessions'")
            ).fetchone()
            if ps_table_exists:
                ps_existing_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(process_sessions)"))}
                if 'resource_percent_at_end' not in ps_existing_cols:
                    conn.execute(text("ALTER TABLE process_sessions ADD COLUMN resource_percent_at_end REAL"))
                    print("[Migration] process_sessions.resource_percent_at_end 컬럼 추가됨")

            incident_table_exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='beholder_incidents'")
            ).fetchone()
            if incident_table_exists:
                incident_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(beholder_incidents)"))}
                for col in ['user_title', 'user_summary', 'user_impact', 'recommended_action', 'available_actions', 'resolution_metadata']:
                    if col not in incident_cols:
                        conn.execute(text(f"ALTER TABLE beholder_incidents ADD COLUMN {col} TEXT"))
                        print(f"[Migration] beholder_incidents.{col} 컬럼 추가됨")

            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS app_runtime_heartbeats ("
                "id INTEGER PRIMARY KEY, "
                "app_instance_id TEXT, "
                "runtime_kind TEXT, "
                "boot_id TEXT, "
                "started_at REAL, "
                "last_heartbeat_at REAL, "
                "last_shutdown_at REAL"
                ")"
            ))

            conn.commit()
    except Exception as e:
        print(f"테이블 스키마 확인/수정 중 오류: {e}")


def start_main_application(instance_manager: SingleInstanceApplication):
    """메인 애플리케이션을 설정하고 실행합니다."""
    # DPI 스케일링 설정은 파일 상단에서 환경 변수로 처리됨 (앱 시작 전에 설정 필요)
    
    app = QApplication(sys.argv)
    app.setApplicationName("숙제 관리자") # 애플리케이션 이름 설정
    app.setOrganizationName("HomeworkHelperOrg") # 조직 이름 설정 (설정 파일 경로 등에 사용될 수 있음)

    # 현재 관리자 권한 상태 로그
    if os.name == 'nt':
        admin_status = "관리자 권한으로 실행 중" if is_admin() else "일반 사용자 권한으로 실행 중"
        print(f"현재 실행 상태: {admin_status}")

    # --- 폰트 설정 ---
    font_path_ttf = get_bundle_resource_path(r"assets\fonts\NEXONLv1GothicOTFBold.otf")
    if os.path.exists(font_path_ttf):
        font_id = QFontDatabase.addApplicationFont(font_path_ttf)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            app.setFont(QFont(font_family, 10))
            print(f"폰트 로드 성공: {font_family}")
        else:
            print("폰트 로드 실패: QFontDatabase.addApplicationFont()가 -1을 반환했습니다.")
    else:
        print(f"폰트 파일 없음: {font_path_ttf}")
    
    app.setQuitOnLastWindowClosed(False) # 마지막 창이 닫혀도 애플리케이션 종료되지 않도록 설정 (트레이 아이콘 사용 시 필수)

    # 데이터 저장 폴더 경로 설정
    data_folder_name = "homework_helper_data"
    if getattr(sys, 'frozen', False): # PyInstaller 등으로 패키징된 경우
        application_path = os.path.dirname(sys.executable)
    else: # 일반 파이썬 스크립트로 실행된 경우
        application_path = os.path.dirname(os.path.abspath(__file__))
    # data_path = os.path.join(application_path, data_folder_name)
    # data_manager_instance = DataManager(data_folder=data_path) # 데이터 매니저 생성
    api_client_instance = ApiClient() # API 클라이언트 생성 (기본 URL: http://127.0.0.1:8000)
    

    # 메인 윈도우 생성 (인스턴스 매니저 전달)
    main_window = MainWindow(api_client_instance, instance_manager=instance_manager)

    # === Graceful Shutdown: signal 및 atexit 핸들러 등록 ===
    def gui_signal_handler(signum, frame):
        """GUI 프로세스가 종료 신호를 받았을 때 안전하게 종료합니다."""
        print(f"\n[GUI] 종료 신호 수신 (Signal: {signum}). Graceful shutdown 시작...")
        main_window.initiate_quit_sequence()

    # Windows에서 지원하는 signal 핸들러 등록
    if os.name == 'nt':
        signal.signal(signal.SIGINT, gui_signal_handler)    # Ctrl+C
        signal.signal(signal.SIGTERM, gui_signal_handler)   # 프로세스 종료 요청
        signal.signal(signal.SIGBREAK, gui_signal_handler)  # Ctrl+Break
        print("[GUI] Signal 핸들러 등록 완료 (SIGINT, SIGTERM, SIGBREAK)")

    # atexit 핸들러 등록 (정상 종료 시 호출)
    # 주의: atexit은 중복 호출을 막기 위해 flag를 사용합니다.
    cleanup_done = {'flag': False}
    def gui_atexit_handler():
        if not cleanup_done['flag']:
            cleanup_done['flag'] = True
            print("[GUI] atexit 핸들러 호출 - 정리 작업 수행")
            # initiate_quit_sequence는 이미 호출되었을 수 있으므로 중복 방지
            # 여기서는 instance_manager cleanup만 수행
            if instance_manager and hasattr(instance_manager, 'cleanup'):
                instance_manager.cleanup()

    atexit.register(gui_atexit_handler)
    print("[GUI] atexit 핸들러 등록 완료")
    # =========================================================

    # IPC 서버 시작 (다른 인스턴스로부터의 활성화 요청 처리용)
    instance_manager.start_ipc_server(main_window_to_activate=main_window)
    main_window.show() # 메인 윈도우 표시
    exit_code = app.exec() # 애플리케이션 이벤트 루프 시작
    stop_api_server()       # GUI 종료 후 API 서버 명시 종료
    sys.exit(exit_code) # 종료 코드로 시스템 종료

if __name__ == "__main__":
    # PyInstaller 다중 프로세스 지원 (필수!)
    import multiprocessing
    multiprocessing.freeze_support()

    if _wants_server_only_mode():
        run_server_main()
        sys.exit(0)

    # 디버깅: _MEIPASS 경로 확인
    if getattr(sys, 'frozen', False):
        meipass_path = getattr(sys, '_MEIPASS', 'N/A')
        print(f"[GUI] _MEIPASS: {meipass_path}")
        print(f"[GUI] PID: {os.getpid()}")

        # === MEI 임시 폴더 정리 ===
        # PyInstaller로 패키징된 경우에만 이전 MEI 폴더를 정리합니다.
        print("\n=== 이전 MEI 임시 폴더 정리 시작 ===")
        cleanup_old_mei_folders()
        print("=== MEI 임시 폴더 정리 완료 ===\n")

    # === 스키마 자동 마이그레이션 ===
    # 앱 업데이트 시 스키마 구조가 변경된 경우 자동으로 마이그레이션합니다.
    # 사용자에게는 보이지 않으며, 실패 시에만 경고를 표시합니다.
    try:
        from src.migration import SchemaMigrator
        print("\n=== 스키마 버전 체크 ===")
        migrator = SchemaMigrator()
        if not migrator.check_and_migrate():
            print("⚠️ 스키마 마이그레이션 실패 - 일부 기능이 제한될 수 있습니다.")
        else:
            print("=== 스키마 체크 완료 ===\n")
    except Exception as e:
        print(f"스키마 마이그레이션 체크 중 오류: {e}")
        # 마이그레이션 실패해도 앱은 계속 실행 (기존 기능은 동작)

    # GUI 애플리케이션 실행
    check_admin_requirement()

    # 단일 인스턴스 실행 확인 로직을 통해 애플리케이션 시작
    def start_primary_application(instance_manager: SingleInstanceApplication):
        # 보조 인스턴스는 기존 창만 활성화해야 하며 API 서버를 건드리면 안 됩니다.
        if not start_api_server():
            sys.exit(1)
        start_main_application(instance_manager)

    run_with_single_instance_check(
        application_name="숙제 관리자",
        main_app_start_callback=start_primary_application
    )
