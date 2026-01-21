"""브라우저에서 HoYoLab 쿠키 자동 추출 유틸리티

Chrome/Edge 브라우저의 쿠키 데이터베이스에서 HoYoLab 관련 쿠키를 추출합니다.
Windows DPAPI와 AES-GCM을 사용하여 암호화된 쿠키 값을 복호화합니다.
"""
import base64
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import webbrowser
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

# PyCryptodome 사용 가능 여부
try:
    from Crypto.Cipher import AES
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    AES = None


class BrowserCookieExtractor:
    """브라우저에서 HoYoLab 쿠키를 자동 추출하는 클래스"""
    
    HOYOLAB_DOMAIN = ".hoyolab.com"
    REQUIRED_COOKIES = ["ltuid_v2", "ltoken_v2", "ltmid_v2"]
    
    # 대체 쿠키 이름 (버전에 따라 다를 수 있음)
    COOKIE_ALIASES = {
        "ltuid_v2": ["ltuid_v2", "ltuid"],
        "ltoken_v2": ["ltoken_v2", "ltoken"],
        "ltmid_v2": ["ltmid_v2", "ltmid"],
    }
    
    def __init__(self):
        """BrowserCookieExtractor 초기화"""
        self._encryption_keys: dict = {}  # 브라우저별 암호화 키 캐시
    
    def extract_from_browser(self, browser: str = "chrome") -> Optional[dict]:
        """Chrome/Edge에서 HoYoLab 쿠키 추출
        
        Args:
            browser: 브라우저 종류 ("chrome" 또는 "edge")
            
        Returns:
            {"ltuid": int, "ltoken_v2": str, "ltmid_v2": str} 또는 None
        """
        if not DPAPI_AVAILABLE:
            logger.error("pywin32가 설치되지 않아 쿠키 추출이 불가능합니다.")
            return None
        
        if not CRYPTO_AVAILABLE:
            logger.error("pycryptodome이 설치되지 않아 쿠키 복호화가 불가능합니다.")
            return None
        
        try:
            # 쿠키 DB 경로 가져오기
            cookie_db_path = self._get_cookie_db_path(browser)
            if not cookie_db_path or not cookie_db_path.exists():
                logger.warning(f"{browser} 쿠키 데이터베이스를 찾을 수 없습니다.")
                return None
            
            # 암호화 키 가져오기
            encryption_key = self._get_encryption_key(browser)
            if not encryption_key:
                logger.error(f"{browser} 암호화 키를 가져올 수 없습니다.")
                return None
            
            # 쿠키 추출
            cookies = self._extract_cookies_from_db(cookie_db_path, encryption_key)
            
            if cookies:
                logger.info(f"{browser}에서 HoYoLab 쿠키 추출 성공")
                return cookies
            else:
                logger.warning(f"{browser}에서 HoYoLab 쿠키를 찾을 수 없습니다.")
                return None
                
        except Exception as e:
            logger.error(f"쿠키 추출 중 오류 발생: {e}")
            return None
    
    def _get_cookie_db_path(self, browser: str) -> Optional[Path]:
        """브라우저 쿠키 DB 경로 반환
        
        Args:
            browser: 브라우저 종류 ("chrome" 또는 "edge")
            
        Returns:
            쿠키 DB 파일 경로 또는 None
        """
        user_profile = os.environ.get("USERPROFILE", "")
        if not user_profile:
            return None
        
        if browser == "chrome":
            return Path(user_profile) / "AppData/Local/Google/Chrome/User Data/Default/Network/Cookies"
        elif browser == "edge":
            return Path(user_profile) / "AppData/Local/Microsoft/Edge/User Data/Default/Network/Cookies"
        else:
            return None
    
    def _get_local_state_path(self, browser: str) -> Optional[Path]:
        """브라우저 Local State 파일 경로 반환
        
        Args:
            browser: 브라우저 종류
            
        Returns:
            Local State 파일 경로 또는 None
        """
        user_profile = os.environ.get("USERPROFILE", "")
        if not user_profile:
            return None
        
        if browser == "chrome":
            return Path(user_profile) / "AppData/Local/Google/Chrome/User Data/Local State"
        elif browser == "edge":
            return Path(user_profile) / "AppData/Local/Microsoft/Edge/User Data/Local State"
        else:
            return None
    
    def _get_encryption_key(self, browser: str) -> Optional[bytes]:
        """Local State 파일에서 암호화 키 추출 및 DPAPI 복호화
        
        Args:
            browser: 브라우저 종류
            
        Returns:
            복호화된 AES 키 또는 None
        """
        # 캐시된 키가 있으면 반환
        if browser in self._encryption_keys:
            return self._encryption_keys[browser]
        
        local_state_path = self._get_local_state_path(browser)
        if not local_state_path or not local_state_path.exists():
            return None
        
        try:
            with open(local_state_path, "r", encoding="utf-8") as f:
                local_state = json.load(f)
            
            # encrypted_key는 base64로 인코딩되어 있고 "DPAPI" 접두사가 붙어있음
            encrypted_key_b64 = local_state.get("os_crypt", {}).get("encrypted_key", "")
            if not encrypted_key_b64:
                return None
            
            encrypted_key = base64.b64decode(encrypted_key_b64)
            
            # "DPAPI" 접두사 제거 (5바이트)
            if encrypted_key[:5] == b"DPAPI":
                encrypted_key = encrypted_key[5:]
            
            # DPAPI로 복호화
            decrypted_key = win32crypt.CryptUnprotectData(
                encrypted_key, None, None, None, 0
            )[1]
            
            # 캐시에 저장
            self._encryption_keys[browser] = decrypted_key
            return decrypted_key
            
        except Exception as e:
            logger.error(f"암호화 키 추출 실패: {e}")
            return None
    
    def _decrypt_cookie_value(self, encrypted_value: bytes, encryption_key: bytes) -> Optional[str]:
        """AES-GCM으로 암호화된 쿠키 값 복호화
        
        Chrome v80 이상은 AES-256-GCM을 사용하여 쿠키를 암호화합니다.
        
        Args:
            encrypted_value: 암호화된 쿠키 값
            encryption_key: AES 키
            
        Returns:
            복호화된 쿠키 값 또는 None
        """
        try:
            # "v10" 또는 "v11" 접두사 확인 (3바이트)
            if encrypted_value[:3] in (b"v10", b"v11"):
                # Nonce (12바이트), 암호문, 인증 태그 (16바이트)
                nonce = encrypted_value[3:15]
                ciphertext = encrypted_value[15:-16]
                tag = encrypted_value[-16:]
                
                cipher = AES.new(encryption_key, AES.MODE_GCM, nonce=nonce)
                decrypted = cipher.decrypt_and_verify(ciphertext, tag)
                return decrypted.decode("utf-8")
            else:
                # 이전 버전 (DPAPI로 직접 암호화)
                decrypted = win32crypt.CryptUnprotectData(
                    encrypted_value, None, None, None, 0
                )[1]
                return decrypted.decode("utf-8")
                
        except Exception as e:
            logger.debug(f"쿠키 복호화 실패: {e}")
            return None
    
    def _extract_cookies_from_db(self, db_path: Path, encryption_key: bytes) -> Optional[dict]:
        """쿠키 DB에서 HoYoLab 쿠키 추출
        
        브라우저가 실행 중이면 DB가 잠겨있으므로 임시 복사본을 사용합니다.
        
        Args:
            db_path: 쿠키 DB 파일 경로
            encryption_key: AES 키
            
        Returns:
            추출된 쿠키 딕셔너리 또는 None
        """
        # 임시 파일로 복사 (브라우저가 DB를 잠그고 있을 수 있음)
        temp_db_path = None
        try:
            temp_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
            os.close(temp_fd)
            shutil.copy2(db_path, temp_db_path)
            
            conn = sqlite3.connect(temp_db_path)
            cursor = conn.cursor()
            
            # HoYoLab 도메인의 쿠키 조회
            cursor.execute("""
                SELECT name, encrypted_value, value
                FROM cookies
                WHERE host_key LIKE ?
            """, (f"%{self.HOYOLAB_DOMAIN}%",))
            
            cookies_found = {}
            for name, encrypted_value, plain_value in cursor.fetchall():
                # 필요한 쿠키인지 확인
                target_key = None
                for key, aliases in self.COOKIE_ALIASES.items():
                    if name in aliases:
                        target_key = key
                        break
                
                if not target_key:
                    continue
                
                # 값 복호화
                value = None
                if plain_value:
                    value = plain_value
                elif encrypted_value:
                    value = self._decrypt_cookie_value(encrypted_value, encryption_key)
                
                if value:
                    cookies_found[target_key] = value
                    logger.debug(f"쿠키 발견: {name}")
            
            conn.close()
            
            # 모든 필수 쿠키가 있는지 확인
            if all(key in cookies_found for key in self.REQUIRED_COOKIES):
                # ltuid를 정수로 변환
                try:
                    cookies_found["ltuid"] = int(cookies_found["ltuid_v2"])
                except (ValueError, KeyError):
                    cookies_found["ltuid"] = 0
                
                return cookies_found
            else:
                missing = [k for k in self.REQUIRED_COOKIES if k not in cookies_found]
                logger.warning(f"일부 필수 쿠키가 없습니다: {missing}")
                return None
                
        except sqlite3.OperationalError as e:
            logger.error(f"쿠키 DB 접근 오류: {e}")
            return None
        except Exception as e:
            logger.error(f"쿠키 추출 오류: {e}")
            return None
        finally:
            # 임시 파일 삭제
            if temp_db_path and os.path.exists(temp_db_path):
                try:
                    os.unlink(temp_db_path)
                except Exception:
                    pass
    
    def open_hoyolab_login(self) -> None:
        """기본 브라우저로 HoYoLab 로그인 페이지 열기"""
        webbrowser.open("https://www.hoyolab.com/home")
        logger.info("HoYoLab 로그인 페이지 열기")
    
    def is_available(self) -> bool:
        """쿠키 추출 기능 사용 가능 여부"""
        return DPAPI_AVAILABLE and CRYPTO_AVAILABLE
