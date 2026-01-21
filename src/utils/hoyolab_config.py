"""HoYoLab 인증 정보 암호화 저장/로드 유틸리티

Windows DPAPI를 사용하여 HoYoLab 쿠키 정보를 안전하게 저장합니다.
이 암호화 방식은 현재 Windows 사용자 계정에 바인딩되어 있습니다.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Windows DPAPI 사용 가능 여부
try:
    import win32crypt
    DPAPI_AVAILABLE = True
except ImportError:
    DPAPI_AVAILABLE = False
    win32crypt = None


class HoYoLabConfig:
    """암호화된 HoYoLab 인증 정보 관리 클래스
    
    Attributes:
        CONFIG_DIR: 설정 파일이 저장되는 디렉토리
        CREDENTIALS_FILE: 암호화된 인증 정보 파일명
    """
    
    CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "HomeworkHelper"
    CREDENTIALS_FILE = "hoyolab_credentials.enc"
    
    def __init__(self):
        """HoYoLabConfig 초기화"""
        self._ensure_config_dir()
    
    def _ensure_config_dir(self) -> None:
        """설정 디렉토리가 없으면 생성"""
        if not self.CONFIG_DIR.exists():
            self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            logger.info(f"설정 디렉토리 생성: {self.CONFIG_DIR}")
    
    @property
    def credentials_path(self) -> Path:
        """암호화된 인증 정보 파일 경로"""
        return self.CONFIG_DIR / self.CREDENTIALS_FILE
    
    def _encrypt_data(self, data: bytes) -> Optional[bytes]:
        """Windows DPAPI를 사용하여 데이터 암호화
        
        Args:
            data: 암호화할 바이트 데이터
            
        Returns:
            암호화된 바이트 데이터 또는 None (실패 시)
        """
        if not DPAPI_AVAILABLE:
            logger.error("Windows DPAPI를 사용할 수 없습니다. pywin32를 설치하세요.")
            return None
        
        try:
            encrypted = win32crypt.CryptProtectData(
                data,
                "HomeworkHelper HoYoLab Credentials",  # 설명 (암호화 시 저장됨)
                None,  # 추가 엔트로피 (사용 안 함)
                None,  # 예약됨
                None,  # 프롬프트 구조체
                0      # 플래그
            )
            return encrypted
        except Exception as e:
            logger.error(f"데이터 암호화 실패: {e}")
            return None
    
    def _decrypt_data(self, encrypted_data: bytes) -> Optional[bytes]:
        """Windows DPAPI를 사용하여 데이터 복호화
        
        Args:
            encrypted_data: 암호화된 바이트 데이터
            
        Returns:
            복호화된 바이트 데이터 또는 None (실패 시)
        """
        if not DPAPI_AVAILABLE:
            logger.error("Windows DPAPI를 사용할 수 없습니다.")
            return None
        
        try:
            _, decrypted = win32crypt.CryptUnprotectData(
                encrypted_data,
                None,  # 추가 엔트로피
                None,  # 예약됨
                None,  # 프롬프트 구조체
                0      # 플래그
            )
            return decrypted
        except Exception as e:
            logger.error(f"데이터 복호화 실패: {e}")
            return None
    
    def save_credentials(
        self,
        ltuid: int,
        ltoken_v2: str,
        ltmid_v2: str,
        starrail_uid: Optional[int] = None,
        zzz_uid: Optional[int] = None
    ) -> bool:
        """HoYoLab 인증 정보를 암호화하여 저장
        
        Args:
            ltuid: HoYoLab 사용자 ID
            ltoken_v2: HoYoLab 인증 토큰
            ltmid_v2: HoYoLab 미들웨어 ID
            starrail_uid: 스타레일 게임 UID (선택)
            zzz_uid: 젠레스 존 제로 게임 UID (선택)
            
        Returns:
            저장 성공 여부
        """
        credentials = {
            "ltuid": ltuid,
            "ltoken_v2": ltoken_v2,
            "ltmid_v2": ltmid_v2,
        }
        
        if starrail_uid:
            credentials["starrail_uid"] = starrail_uid
        if zzz_uid:
            credentials["zzz_uid"] = zzz_uid
        
        try:
            # JSON으로 직렬화
            json_data = json.dumps(credentials, ensure_ascii=False)
            data_bytes = json_data.encode("utf-8")
            
            # 암호화
            encrypted = self._encrypt_data(data_bytes)
            if not encrypted:
                return False
            
            # 파일에 저장
            self.credentials_path.write_bytes(encrypted)
            logger.info(f"HoYoLab 인증 정보 저장 완료: {self.credentials_path}")
            return True
            
        except Exception as e:
            logger.error(f"인증 정보 저장 실패: {e}")
            return False
    
    def load_credentials(self) -> Optional[dict]:
        """암호화된 HoYoLab 인증 정보 로드
        
        Returns:
            인증 정보 딕셔너리 또는 None (파일 없거나 복호화 실패 시)
        """
        if not self.credentials_path.exists():
            logger.debug("HoYoLab 인증 정보 파일이 없습니다.")
            return None
        
        try:
            # 파일에서 읽기
            encrypted_data = self.credentials_path.read_bytes()
            
            # 복호화
            decrypted = self._decrypt_data(encrypted_data)
            if not decrypted:
                return None
            
            # JSON 파싱
            json_data = decrypted.decode("utf-8")
            credentials = json.loads(json_data)
            
            logger.debug("HoYoLab 인증 정보 로드 완료")
            return credentials
            
        except Exception as e:
            logger.error(f"인증 정보 로드 실패: {e}")
            return None
    
    def clear_credentials(self) -> bool:
        """저장된 HoYoLab 인증 정보 삭제
        
        Returns:
            삭제 성공 여부
        """
        try:
            if self.credentials_path.exists():
                self.credentials_path.unlink()
                logger.info("HoYoLab 인증 정보 삭제 완료")
            return True
        except Exception as e:
            logger.error(f"인증 정보 삭제 실패: {e}")
            return False
    
    def is_configured(self) -> bool:
        """HoYoLab 인증 정보가 설정되어 있는지 확인
        
        Returns:
            인증 정보가 유효하게 설정되어 있으면 True
        """
        credentials = self.load_credentials()
        if not credentials:
            return False
        
        # 필수 필드 확인
        ltuid = credentials.get("ltuid")
        ltoken = credentials.get("ltoken_v2")
        
        return bool(ltuid and ltoken)
