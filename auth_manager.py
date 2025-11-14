# auth_manager.py

import json
import os
from typing import Optional
from pathlib import Path

class AuthManager:
    """
    JWT 토큰 및 사용자 인증 정보를 관리하는 클래스

    토큰을 로컬 파일에 저장하고 로드합니다.
    추후 Windows Credential Manager 등으로 업그레이드 가능
    """

    def __init__(self, data_folder: str = "homework_helper_data"):
        """
        Args:
            data_folder: 인증 데이터를 저장할 폴더 경로
        """
        # 사용자 데이터 폴더 경로 설정
        base_path = Path.home() / data_folder
        base_path.mkdir(parents=True, exist_ok=True)

        self.auth_file_path = base_path / "auth_token.json"
        self.token: Optional[str] = None
        self.user_id: Optional[int] = None
        self.username: Optional[str] = None

        # 저장된 토큰 자동 로드
        self.load_token()

    def save_token(self, token: str, user_id: int, username: str) -> bool:
        """
        JWT 토큰과 사용자 정보를 파일에 저장

        Args:
            token: JWT 액세스 토큰
            user_id: 사용자 ID
            username: 사용자 이름

        Returns:
            저장 성공 여부
        """
        try:
            auth_data = {
                "token": token,
                "user_id": user_id,
                "username": username
            }

            with open(self.auth_file_path, 'w', encoding='utf-8') as f:
                json.dump(auth_data, f, ensure_ascii=False, indent=2)

            # 메모리에도 저장
            self.token = token
            self.user_id = user_id
            self.username = username

            print(f"[AuthManager] 토큰 저장 완료: user={username} (ID={user_id})")
            return True

        except Exception as e:
            print(f"[AuthManager] 토큰 저장 실패: {e}")
            return False

    def load_token(self) -> bool:
        """
        파일에서 저장된 JWT 토큰 로드

        Returns:
            로드 성공 여부
        """
        try:
            if not self.auth_file_path.exists():
                print("[AuthManager] 저장된 토큰 없음")
                return False

            with open(self.auth_file_path, 'r', encoding='utf-8') as f:
                auth_data = json.load(f)

            self.token = auth_data.get("token")
            self.user_id = auth_data.get("user_id")
            self.username = auth_data.get("username")

            if self.token:
                print(f"[AuthManager] 토큰 로드 완료: user={self.username}")
                return True
            else:
                print("[AuthManager] 토큰이 비어있음")
                return False

        except Exception as e:
            print(f"[AuthManager] 토큰 로드 실패: {e}")
            return False

    def clear_token(self) -> bool:
        """
        저장된 토큰 삭제 (로그아웃)

        Returns:
            삭제 성공 여부
        """
        try:
            if self.auth_file_path.exists():
                self.auth_file_path.unlink()

            # 메모리도 초기화
            self.token = None
            self.user_id = None
            self.username = None

            print("[AuthManager] 토큰 삭제 완료 (로그아웃)")
            return True

        except Exception as e:
            print(f"[AuthManager] 토큰 삭제 실패: {e}")
            return False

    def is_authenticated(self) -> bool:
        """
        현재 인증 상태 확인

        Returns:
            토큰이 존재하면 True
        """
        return self.token is not None and self.token != ""

    def get_auth_header(self) -> dict:
        """
        HTTP Authorization 헤더 생성

        Returns:
            {"Authorization": "Bearer <token>"} 형식의 딕셔너리
        """
        if not self.is_authenticated():
            return {}

        return {
            "Authorization": f"Bearer {self.token}"
        }
