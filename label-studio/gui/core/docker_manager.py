#!/usr/bin/env python3
"""
Docker 관리 모듈
Label Studio Docker 컨테이너 제어 및 상태 모니터링
"""

import subprocess
import os
import time
import requests
from pathlib import Path
from typing import Optional, Tuple, List
from enum import Enum


class DockerStatus(Enum):
    """Docker 상태"""
    NOT_INSTALLED = "not_installed"
    NOT_RUNNING = "not_running"
    RUNNING = "running"


class LabelStudioStatus(Enum):
    """Label Studio 상태"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class DockerManager:
    """Docker 및 Label Studio 컨테이너 관리자"""

    def __init__(self, docker_compose_path: Optional[Path] = None):
        """
        Docker 관리자 초기화

        Args:
            docker_compose_path: docker-compose.yml 파일 경로
        """
        if docker_compose_path is None:
            # 기본 경로: label-studio/docker-compose.yml
            self.docker_compose_path = Path(__file__).parent.parent.parent / "docker-compose.yml"
        else:
            self.docker_compose_path = docker_compose_path

        self.label_studio_url = "http://localhost:8080"

    def check_docker_installed(self) -> bool:
        """Docker가 설치되어 있는지 확인"""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def check_docker_running(self) -> bool:
        """Docker 데몬이 실행 중인지 확인"""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def get_docker_status(self) -> DockerStatus:
        """Docker 상태 반환"""
        if not self.check_docker_installed():
            return DockerStatus.NOT_INSTALLED

        if not self.check_docker_running():
            return DockerStatus.NOT_RUNNING

        return DockerStatus.RUNNING

    def check_label_studio_running(self) -> bool:
        """Label Studio 컨테이너가 실행 중인지 확인"""
        try:
            # docker-compose ps로 컨테이너 상태 확인
            result = subprocess.run(
                ["docker-compose", "ps", "-q"],
                cwd=self.docker_compose_path.parent,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            # 컨테이너 ID가 있으면 실행 중
            return bool(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def check_label_studio_accessible(self) -> bool:
        """Label Studio 웹 서버가 접근 가능한지 확인 (HTTP)"""
        try:
            response = requests.get(self.label_studio_url, timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def get_label_studio_status(self) -> LabelStudioStatus:
        """Label Studio 상태 반환"""
        if not self.check_label_studio_running():
            return LabelStudioStatus.STOPPED

        if self.check_label_studio_accessible():
            return LabelStudioStatus.RUNNING

        # 컨테이너는 실행 중이지만 웹 서버 응답 없음 (시작 중 or 에러)
        return LabelStudioStatus.STARTING

    def start_label_studio(self) -> Tuple[bool, str]:
        """
        Label Studio 컨테이너 시작

        Returns:
            (성공 여부, 메시지)
        """
        # Docker 상태 확인
        docker_status = self.get_docker_status()
        if docker_status == DockerStatus.NOT_INSTALLED:
            return False, "Docker가 설치되어 있지 않습니다."
        if docker_status == DockerStatus.NOT_RUNNING:
            return False, "Docker가 실행되지 않았습니다. Docker Desktop을 먼저 실행해주세요."

        # 이미 실행 중인지 확인
        if self.check_label_studio_running():
            return True, "Label Studio가 이미 실행 중입니다."

        # docker-compose.yml 파일 확인
        if not self.docker_compose_path.exists():
            return False, f"docker-compose.yml 파일을 찾을 수 없습니다: {self.docker_compose_path}"

        try:
            # docker-compose up -d 실행
            result = subprocess.run(
                ["docker-compose", "up", "-d"],
                cwd=self.docker_compose_path.parent,
                capture_output=True,
                text=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode != 0:
                error_msg = result.stderr if result.stderr else result.stdout
                return False, f"Label Studio 시작 실패:\n{error_msg}"

            # 서버가 준비될 때까지 대기 (최대 30초)
            for i in range(30):
                time.sleep(1)
                if self.check_label_studio_accessible():
                    return True, "Label Studio가 성공적으로 시작되었습니다."

            # 타임아웃
            return True, "Label Studio 컨테이너가 시작되었지만 웹 서버 응답이 없습니다. 잠시 후 다시 시도해주세요."

        except subprocess.TimeoutExpired:
            return False, "Label Studio 시작 시간 초과 (60초)"
        except Exception as e:
            return False, f"Label Studio 시작 중 오류 발생: {e}"

    def stop_label_studio(self) -> Tuple[bool, str]:
        """
        Label Studio 컨테이너 중지

        Returns:
            (성공 여부, 메시지)
        """
        # 실행 중인지 확인
        if not self.check_label_studio_running():
            return True, "Label Studio가 이미 중지되어 있습니다."

        try:
            # docker-compose down 실행
            result = subprocess.run(
                ["docker-compose", "down"],
                cwd=self.docker_compose_path.parent,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode != 0:
                error_msg = result.stderr if result.stderr else result.stdout
                return False, f"Label Studio 중지 실패:\n{error_msg}"

            return True, "Label Studio가 성공적으로 중지되었습니다."

        except subprocess.TimeoutExpired:
            return False, "Label Studio 중지 시간 초과 (30초)"
        except Exception as e:
            return False, f"Label Studio 중지 중 오류 발생: {e}"

    def get_logs(self, lines: int = 100) -> List[str]:
        """
        Label Studio 컨테이너 로그 가져오기

        Args:
            lines: 가져올 로그 줄 수

        Returns:
            로그 라인 리스트
        """
        try:
            result = subprocess.run(
                ["docker-compose", "logs", "--tail", str(lines)],
                cwd=self.docker_compose_path.parent,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode == 0:
                return result.stdout.splitlines()
            else:
                return [f"로그 가져오기 실패: {result.stderr}"]

        except subprocess.TimeoutExpired:
            return ["로그 가져오기 시간 초과"]
        except Exception as e:
            return [f"로그 가져오기 오류: {e}"]

    def open_browser(self) -> bool:
        """
        Label Studio 웹 페이지를 기본 브라우저로 열기

        Returns:
            성공 여부
        """
        try:
            import webbrowser
            webbrowser.open(self.label_studio_url)
            return True
        except Exception as e:
            print(f"브라우저 열기 실패: {e}")
            return False

    def get_container_info(self) -> dict:
        """
        Label Studio 컨테이너 정보 반환

        Returns:
            컨테이너 정보 딕셔너리
        """
        try:
            result = subprocess.run(
                ["docker-compose", "ps", "--format", "json"],
                cwd=self.docker_compose_path.parent,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )

            if result.returncode == 0 and result.stdout.strip():
                import json
                return json.loads(result.stdout)
            else:
                return {}

        except Exception as e:
            print(f"컨테이너 정보 가져오기 실패: {e}")
            return {}
