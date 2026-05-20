"""브라우저 쿠키 자동 추출 유틸리티.

HoYoLab과 BlablaLink/NIKKE처럼 브라우저 로그인 세션을 읽기 전용 API 호출에
재사용해야 하는 provider의 쿠키를 Chrome/Edge/Firefox 프로필에서 추출합니다.

- Chromium 계열은 Windows DPAPI + AES-GCM 복호화를 사용합니다.
- Firefox는 쿠키 값이 별도 OS 암호화 없이 SQLite에 저장되므로 pywin32/crypto
  설치 여부와 무관하게 동작합니다.
- 실행 중인 브라우저의 최신 쿠키를 놓치지 않도록 SQLite WAL/SHM 파일도 함께
  임시 디렉터리로 복사해 읽습니다.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
import webbrowser
from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

try:
    import win32crypt
    DPAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - Windows host dependency
    DPAPI_AVAILABLE = False
    win32crypt = None

try:
    from Crypto.Cipher import AES
    CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    CRYPTO_AVAILABLE = False
    AES = None


@dataclass(frozen=True)
class CookieProviderSpec:
    provider: str
    domains: tuple[str, ...]
    required: tuple[str, ...]
    aliases: dict[str, tuple[str, ...]]
    keep_all_cookies: bool = False


class BrowserCookieExtractor:
    """브라우저 프로필에서 provider별 인증 쿠키를 추출합니다."""

    HOYOLAB_PROVIDER = "hoyolab"
    NIKKE_PROVIDER = "nikke_blablalink"
    DEFAULT_PROVIDER = HOYOLAB_PROVIDER

    PROVIDERS: dict[str, CookieProviderSpec] = {
        HOYOLAB_PROVIDER: CookieProviderSpec(
            provider=HOYOLAB_PROVIDER,
            domains=(".hoyolab.com", "hoyolab.com"),
            # ltmid_v2는 최근 환경에서 없을 수 있으므로 필수에서 제외합니다.
            required=("ltuid_v2", "ltoken_v2"),
            aliases={
                "ltuid_v2": ("ltuid_v2", "ltuid"),
                "ltoken_v2": ("ltoken_v2", "ltoken"),
                "ltmid_v2": ("ltmid_v2", "ltmid"),
            },
            keep_all_cookies=False,
        ),
        NIKKE_PROVIDER: CookieProviderSpec(
            provider=NIKKE_PROVIDER,
            domains=(".blablalink.com", "blablalink.com", "www.blablalink.com", "api.blablalink.com"),
            required=(),
            aliases={},
            keep_all_cookies=True,
        ),
    }

    # 하위 호환 상수
    HOYOLAB_DOMAIN = ".hoyolab.com"
    REQUIRED_COOKIES = ["ltuid_v2", "ltoken_v2"]
    COOKIE_ALIASES = {
        "ltuid_v2": ["ltuid_v2", "ltuid"],
        "ltoken_v2": ["ltoken_v2", "ltoken"],
        "ltmid_v2": ["ltmid_v2", "ltmid"],
    }

    def __init__(self):
        self._encryption_keys: dict[str, bytes] = {}

    def extract_from_browser(self, browser: str = "chrome", provider: str = DEFAULT_PROVIDER) -> Optional[dict[str, Any]]:
        """브라우저에서 provider 쿠키를 추출합니다.

        Args:
            browser: ``chrome``, ``edge`` 또는 ``firefox``.
            provider: ``hoyolab`` 또는 ``nikke_blablalink``.

        Returns:
            HoYoLab: ``{"ltuid": int, "ltuid_v2": str, "ltoken_v2": str, ...}``
            NIKKE: ``{"cookies": dict, "cookie_header": str, ...}``
            실패 시 ``None``.
        """
        browser = (browser or "").strip().lower()
        spec = self._provider_spec(provider)

        if browser == "firefox":
            return self._extract_from_firefox(spec)

        if browser not in {"chrome", "edge"}:
            logger.error("지원하지 않는 브라우저입니다: %s", browser)
            return None

        if not DPAPI_AVAILABLE:
            logger.error("pywin32가 설치되지 않아 %s 쿠키 복호화가 불가능합니다.", browser)
            return None
        if not CRYPTO_AVAILABLE:
            logger.error("pycryptodome이 설치되지 않아 %s 쿠키 복호화가 불가능합니다.", browser)
            return None

        try:
            cookie_db_path = self._get_cookie_db_path(browser)
            if not cookie_db_path or not cookie_db_path.exists():
                logger.warning("%s 쿠키 데이터베이스를 찾을 수 없습니다.", browser)
                return None

            encryption_key = self._get_encryption_key(browser)
            if not encryption_key:
                logger.error("%s 암호화 키를 가져올 수 없습니다.", browser)
                return None

            cookies = self._extract_cookies_from_chromium_db(cookie_db_path, encryption_key, spec)
            if cookies:
                logger.info("%s에서 %s 쿠키 추출 성공", browser, spec.provider)
                return cookies

            logger.warning("%s에서 %s 쿠키를 찾을 수 없습니다.", browser, spec.provider)
            return None
        except Exception as exc:  # pragma: no cover - defensive GUI boundary
            logger.error("쿠키 추출 중 오류 발생: %s", exc)
            return None

    def _provider_spec(self, provider: str) -> CookieProviderSpec:
        spec = self.PROVIDERS.get(provider)
        if spec is None:
            raise ValueError(f"지원하지 않는 쿠키 provider입니다: {provider}")
        return spec

    def _get_cookie_db_path(self, browser: str) -> Optional[Path]:
        user_profile = os.environ.get("USERPROFILE", "")
        if not user_profile:
            return None

        if browser == "chrome":
            return Path(user_profile) / "AppData/Local/Google/Chrome/User Data/Default/Network/Cookies"
        if browser == "edge":
            return Path(user_profile) / "AppData/Local/Microsoft/Edge/User Data/Default/Network/Cookies"
        return None

    def _get_firefox_profiles_dir(self) -> Optional[Path]:
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return None
        return Path(appdata) / "Mozilla/Firefox/Profiles"

    def _get_firefox_default_profile(self) -> Optional[Path]:
        profiles = self._iter_firefox_profiles()
        return profiles[0] if profiles else None

    def _iter_firefox_profiles(self) -> list[Path]:
        """Firefox profiles.ini를 기준으로 가능한 모든 프로필을 반환합니다."""
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return []

        firefox_root = Path(appdata) / "Mozilla/Firefox"
        profiles_ini = firefox_root / "profiles.ini"
        profiles: list[Path] = []

        if profiles_ini.exists():
            try:
                config = ConfigParser()
                config.read(profiles_ini, encoding="utf-8")

                default_profiles: list[Path] = []
                other_profiles: list[Path] = []
                for section in config.sections():
                    if not section.startswith("Profile"):
                        continue
                    path_value = config.get(section, "Path", fallback="")
                    if not path_value:
                        continue
                    is_relative = config.get(section, "IsRelative", fallback="1") == "1"
                    profile_path = firefox_root / path_value if is_relative else Path(path_value)
                    if config.get(section, "Default", fallback="0") == "1":
                        default_profiles.append(profile_path)
                    else:
                        other_profiles.append(profile_path)
                profiles.extend(default_profiles)
                profiles.extend(other_profiles)
            except Exception as exc:
                logger.error("Firefox 프로필 파싱 실패: %s", exc)

        profiles_dir = self._get_firefox_profiles_dir()
        if profiles_dir and profiles_dir.exists():
            for candidate in sorted(profiles_dir.iterdir()):
                if candidate.is_dir() and candidate not in profiles:
                    profiles.append(candidate)

        return [profile for profile in profiles if (profile / "cookies.sqlite").exists()]

    def _extract_from_firefox(self, spec: CookieProviderSpec | None = None) -> Optional[dict[str, Any]]:
        spec = spec or self._provider_spec(self.HOYOLAB_PROVIDER)
        profiles = self._iter_firefox_profiles()
        if not profiles:
            logger.warning("Firefox 쿠키 프로필을 찾을 수 없습니다.")
            return None

        best_result: Optional[dict[str, Any]] = None
        inspected: list[str] = []
        for profile_path in profiles:
            inspected.append(profile_path.name)
            cookie_db = profile_path / "cookies.sqlite"
            temp_dir: Optional[str] = None
            try:
                temp_db_path, temp_dir = self._copy_sqlite_bundle(cookie_db)
                found = self._query_firefox_cookie_records(temp_db_path, spec)
                result = self._normalise_provider_cookies(found, spec)
                if result:
                    result.setdefault("browser", "firefox")
                    result.setdefault("profile", profile_path.name)
                    logger.info("Firefox 프로필 %s에서 %s 쿠키 추출 성공", profile_path.name, spec.provider)
                    return result
                if found and best_result is None:
                    # 필수 쿠키가 모자란 경우에도 진단용 후보 수를 보존합니다.
                    best_result = {"provider": spec.provider, "cookie_count": len(found), "profile": profile_path.name}
            except Exception as exc:
                logger.error("Firefox 쿠키 추출 오류(%s): %s", profile_path.name, exc)
            finally:
                if temp_dir:
                    shutil.rmtree(temp_dir, ignore_errors=True)

        logger.warning("Firefox에서 %s 필수 쿠키를 찾지 못했습니다. inspected=%s", spec.provider, inspected)
        return None if not best_result or spec.required else best_result

    def _copy_sqlite_bundle(self, db_path: Path) -> tuple[Path, str]:
        temp_dir = tempfile.mkdtemp(prefix="hh-cookies-")
        temp_db_path = Path(temp_dir) / db_path.name
        shutil.copy2(db_path, temp_db_path)
        for suffix in ("-wal", "-shm"):
            sibling = Path(str(db_path) + suffix)
            if sibling.exists():
                shutil.copy2(sibling, Path(str(temp_db_path) + suffix))
        return temp_db_path, temp_dir

    def _query_firefox_cookie_records(self, db_path: Path, spec: CookieProviderSpec) -> dict[str, dict[str, Any]]:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            rows: list[tuple[Any, ...]] = []
            for pattern in self._domain_like_patterns(spec):
                cursor.execute(
                    """
                    SELECT host, name, value, path, expiry, lastAccessed, creationTime
                    FROM moz_cookies
                    WHERE host LIKE ?
                    """,
                    (pattern,),
                )
                rows.extend(cursor.fetchall())
        return self._records_from_rows(rows, encrypted=False)

    def _extract_cookies_from_chromium_db(
        self,
        db_path: Path,
        encryption_key: bytes,
        spec: CookieProviderSpec,
    ) -> Optional[dict[str, Any]]:
        temp_dir: Optional[str] = None
        try:
            temp_db_path, temp_dir = self._copy_sqlite_bundle(db_path)
            with sqlite3.connect(temp_db_path) as conn:
                cursor = conn.cursor()
                rows: list[tuple[Any, ...]] = []
                for pattern in self._domain_like_patterns(spec):
                    cursor.execute(
                        """
                        SELECT host_key, name, encrypted_value, value, path, expires_utc, last_access_utc, creation_utc
                        FROM cookies
                        WHERE host_key LIKE ?
                        """,
                        (pattern,),
                    )
                    rows.extend(cursor.fetchall())

            found: dict[str, dict[str, Any]] = {}
            now = time.time()
            for host, name, encrypted_value, plain_value, path, expires_utc, last_access, creation in rows:
                value = plain_value or None
                if not value and encrypted_value:
                    value = self._decrypt_cookie_value(encrypted_value, encryption_key)
                if not value:
                    continue
                found[name] = {
                    "name": name,
                    "value": value,
                    "domain": host,
                    "path": path,
                    "expires": expires_utc,
                    "last_accessed": last_access or creation or now,
                }

            return self._normalise_provider_cookies(found, spec)
        except sqlite3.OperationalError as exc:
            logger.error("쿠키 DB 접근 오류: %s", exc)
            return None
        except Exception as exc:
            logger.error("쿠키 추출 오류: %s", exc)
            return None
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _domain_like_patterns(self, spec: CookieProviderSpec) -> list[str]:
        patterns: list[str] = []
        for domain in spec.domains:
            bare = domain.lstrip(".")
            pattern = f"%{bare}%"
            if pattern not in patterns:
                patterns.append(pattern)
        return patterns

    def _records_from_rows(self, rows: list[tuple[Any, ...]], *, encrypted: bool) -> dict[str, dict[str, Any]]:
        del encrypted  # Firefox rows are plain; kept for call-site readability.
        found: dict[str, dict[str, Any]] = {}
        now = int(time.time())
        for host, name, value, path, expiry, last_accessed, creation_time in rows:
            if expiry and int(expiry) < now:
                continue
            if not value:
                continue
            previous = found.get(name)
            candidate_rank = last_accessed or creation_time or 0
            previous_rank = previous.get("last_accessed", 0) if previous else -1
            if previous is not None and previous_rank > candidate_rank:
                continue
            found[name] = {
                "name": name,
                "value": value,
                "domain": host,
                "path": path,
                "expires": expiry,
                "last_accessed": candidate_rank,
            }
        return found

    def _normalise_provider_cookies(
        self,
        found: dict[str, dict[str, Any]],
        spec: CookieProviderSpec,
    ) -> Optional[dict[str, Any]]:
        if not found:
            return None

        if spec.keep_all_cookies:
            cookies = {name: record["value"] for name, record in sorted(found.items()) if record.get("value")}
            if not cookies:
                return None
            return {
                "provider": spec.provider,
                "cookies": cookies,
                "cookie_header": self.cookie_header(cookies),
                "cookie_count": len(cookies),
                "domains": sorted({str(record.get("domain") or "") for record in found.values()}),
            }

        normalised: dict[str, Any] = {"provider": spec.provider}
        raw_cookies = {name: record["value"] for name, record in found.items() if record.get("value")}
        for target_key, aliases in spec.aliases.items():
            for alias in aliases:
                if alias in raw_cookies and raw_cookies[alias]:
                    normalised[target_key] = raw_cookies[alias]
                    break

        missing = [key for key in spec.required if not normalised.get(key)]
        if missing:
            logger.warning("%s 필수 쿠키가 없습니다: %s", spec.provider, missing)
            return None

        ltuid_value = normalised.get("ltuid_v2") or normalised.get("ltuid")
        try:
            normalised["ltuid"] = int(ltuid_value)
        except (TypeError, ValueError):
            normalised["ltuid"] = 0

        normalised["cookies"] = raw_cookies
        normalised["cookie_header"] = self.cookie_header(raw_cookies)
        normalised["cookie_count"] = len(raw_cookies)
        return normalised

    @staticmethod
    def cookie_header(cookies: dict[str, Any]) -> str:
        """requests 헤더에 넣을 수 있는 Cookie 문자열을 생성합니다."""
        parts = []
        for name, value in sorted(cookies.items()):
            if value is None:
                continue
            parts.append(f"{quote(str(name), safe='')}={quote(str(value), safe='!#$%&\'()*+-./:<=>?@[]^_`{|}~')}")
        return "; ".join(parts)

    def _get_local_state_path(self, browser: str) -> Optional[Path]:
        user_profile = os.environ.get("USERPROFILE", "")
        if not user_profile:
            return None

        if browser == "chrome":
            return Path(user_profile) / "AppData/Local/Google/Chrome/User Data/Local State"
        if browser == "edge":
            return Path(user_profile) / "AppData/Local/Microsoft/Edge/User Data/Local State"
        return None

    def _get_encryption_key(self, browser: str) -> Optional[bytes]:
        if browser in self._encryption_keys:
            return self._encryption_keys[browser]

        local_state_path = self._get_local_state_path(browser)
        if not local_state_path or not local_state_path.exists():
            return None

        try:
            local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
            encrypted_key_b64 = local_state.get("os_crypt", {}).get("encrypted_key", "")
            if not encrypted_key_b64:
                return None

            encrypted_key = base64.b64decode(encrypted_key_b64)
            if encrypted_key[:5] == b"DPAPI":
                encrypted_key = encrypted_key[5:]

            decrypted_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
            self._encryption_keys[browser] = decrypted_key
            return decrypted_key
        except Exception as exc:
            logger.error("암호화 키 추출 실패: %s", exc)
            return None

    def _decrypt_cookie_value(self, encrypted_value: bytes, encryption_key: bytes) -> Optional[str]:
        try:
            encrypted = bytes(encrypted_value)
            if encrypted[:3] in (b"v10", b"v11"):
                nonce = encrypted[3:15]
                ciphertext = encrypted[15:-16]
                tag = encrypted[-16:]
                cipher = AES.new(encryption_key, AES.MODE_GCM, nonce=nonce)
                decrypted = cipher.decrypt_and_verify(ciphertext, tag)
                return decrypted.decode("utf-8")

            decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1]
            return decrypted.decode("utf-8")
        except Exception as exc:
            logger.debug("쿠키 복호화 실패: %s", exc)
            return None

    def open_hoyolab_login(self) -> None:
        webbrowser.open("https://www.hoyolab.com/home")
        logger.info("HoYoLab 로그인 페이지 열기")

    def open_nikke_login(self) -> None:
        webbrowser.open("https://www.blablalink.com/login")
        logger.info("BlablaLink 로그인 페이지 열기")

    def is_available(self, browser: str | None = None) -> bool:
        """쿠키 추출 기능 사용 가능 여부.

        Firefox는 DPAPI/pycryptodome 없이도 읽을 수 있으므로 브라우저별로 판단합니다.
        ``browser``를 생략하면 하나 이상의 지원 경로가 가능한지 반환합니다.
        """
        if browser:
            browser = browser.lower()
            if browser == "firefox":
                return bool(self._iter_firefox_profiles() or self._get_firefox_profiles_dir())
            if browser in {"chrome", "edge"}:
                return DPAPI_AVAILABLE and CRYPTO_AVAILABLE
            return False
        return (DPAPI_AVAILABLE and CRYPTO_AVAILABLE) or bool(self._get_firefox_profiles_dir())
