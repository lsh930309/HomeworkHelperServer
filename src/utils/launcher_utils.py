# -*- coding: utf-8 -*-
"""
런처 프로세스의 안전한 재시작을 위한 유틸리티 함수 모음.

주요 기능:
- 런처의 다운로드 상태 감지
- 런처를 통해 실행된 게임 프로세스 감지
- 재시작 안전성 여부 판단
"""

import time
from typing import Optional
import psutil


def is_launcher_downloading(
    process: psutil.Process, interval: float = 2.0, threshold_mbps: float = 1.0
) -> bool:
    """
    프로세스의 I/O 읽기 속도를 모니터링하여 다운로드 중인지 확인합니다.

    Args:
        process: 모니터링할 psutil.Process 객체.
        interval: I/O를 측정할 시간 간격(초). 0보다 커야 합니다.
        threshold_mbps: "다운로드 중"으로 간주할 임계값 (Mbps).

    Returns:
        읽기 속도가 임계값을 초과하면 True, 그렇지 않으면 False.
    """
    if not interval > 0:
        raise ValueError("측정 간격(interval)은 0보다 커야 합니다.")
    try:
        # io_counters는 네트워크 I/O를 포함합니다.
        initial_bytes = process.io_counters().read_bytes
        time.sleep(interval)
        final_bytes = process.io_counters().read_bytes

        # 초당 바이트 계산
        bytes_per_second = (final_bytes - initial_bytes) / interval
        # Mbps로 변환 (1 byte = 8 bits, 1 Mbps = 1,000,000 bps)
        mbps = (bytes_per_second * 8) / 1_000_000

        print(
            f"[LauncherUtils] {process.name()} (PID: {process.pid})의 I/O 읽기 속도: {mbps:.2f} Mbps"
        )
        return mbps > threshold_mbps
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        print(f"[LauncherUtils] 프로세스(PID: {process.pid})의 I/O 카운터에 접근할 수 없습니다.")
        return False


def is_game_running_from_launcher(launcher_process: psutil.Process) -> bool:
    """
    런처의 자식 프로세스로 실행 중인 게임이 있는지 확인합니다.

    Args:
        launcher_process: 확인할 런처의 psutil.Process 객체.

    Returns:
        잠재적인 게임 프로세스가 발견되면 True, 그렇지 않으면 False.
    """
    # 런처들의 일반적인 헬퍼 실행 파일 목록 (소문자)
    known_helpers = [
        "steamwebhelper.exe",
        "streaming_client.exe",
        "epicwebhelper.exe",
        "crashreportclient.exe",  # Epic Games
        "battle.net helper.exe",
        "agent.exe",  # Blizzard
        "eossdk-win64-shipping.exe",  # Epic Online Services
    ]

    try:
        # 모든 자손 프로세스를 재귀적으로 가져옵니다.
        descendants = launcher_process.children(recursive=True)
        if not descendants:
            return False

        for child in descendants:
            try:
                child_name = child.name().lower()
                # 자손 프로세스가 알려진 헬퍼가 아니라면,
                # 게임 또는 게임과 관련된 중요한 프로세스로 간주합니다.
                if child_name not in known_helpers:
                    print(
                        f"[LauncherUtils] 잠재적인 게임 프로세스 발견: {child.name()} (PID: {child.pid})"
                    )
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # 확인 중 자식 프로세스가 종료될 수 있으므로 계속 진행합니다.
                continue

    except (psutil.NoSuchProcess, psutil.AccessDenied):
        print(f"[LauncherUtils] 런처 프로세스(PID: {launcher_process.pid})에 접근할 수 없습니다.")
        return False

    return False


def should_restart_launcher(
    launcher_process: psutil.Process, download_threshold_mbps: float = 1.0
) -> bool:
    """
    활성 다운로드나 실행 중인 게임이 있는지 확인하여 런처 프로세스를 재시작해도 안전한지 결정합니다.

    Args:
        launcher_process: 확인할 런처의 psutil.Process 객체.
        download_threshold_mbps: 다운로드로 간주할 네트워크 사용량 임계값.

    Returns:
        재시작이 안전하면 True, 그렇지 않으면 False.
    """
    try:
        launcher_name = launcher_process.name()
        print(
            f"\n[LauncherUtils] {launcher_name} (PID: {launcher_process.pid}) 재시작 안전성 검사 시작"
        )

        # 검사 1: 이 런처에서 실행한 게임이 있는가?
        if is_game_running_from_launcher(launcher_process):
            print(
                f"[LauncherUtils] 재시작 불안전: {launcher_name}에서 실행한 게임이 실행 중입니다."
            )
            return False

        # 검사 2: 런처가 다운로드 중인가? (시간이 걸리는 검사라 나중에 수행)
        if is_launcher_downloading(
            launcher_process, threshold_mbps=download_threshold_mbps
        ):
            print(f"[LauncherUtils] 재시작 불안전: {launcher_name}가 다운로드 중입니다.")
            return False

        print(f"[LauncherUtils] {launcher_name} 재시작이 안전합니다.")
        return True

    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        print(f"[LauncherUtils] 런처 프로세스 검사 중 오류 발생: {e}")
        return False
