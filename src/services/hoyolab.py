"""HoYoLab API 연동 서비스

호요버스 게임 스태미나(개척력/배터리) 정보를 조회하는 서비스 클래스.
genshin.py 라이브러리를 사용하여 HoYoLab API와 통신합니다.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

try:
    import genshin
    GENSHIN_AVAILABLE = True
except ImportError:
    GENSHIN_AVAILABLE = False
    genshin = None

from src.utils.hoyolab_config import HoYoLabConfig

logger = logging.getLogger(__name__)


@dataclass
class StaminaInfo:
    """스태미나 정보 데이터 클래스"""
    game_id: str           # "honkai_starrail" 또는 "zenless_zone_zero"
    game_name: str         # "붕괴: 스타레일" 또는 "젠레스 존 제로"
    current: int           # 현재 스태미나
    max: int               # 최대 스태미나
    recover_time: int      # 완전 회복까지 남은 시간(초)
    full_time: Optional[datetime]  # 스태미나 완전 회복 예상 시각
    updated_at: datetime   # 데이터 조회 시각


class HoYoLabService:
    """HoYoLab API 서비스 클래스
    
    호요버스 게임(스타레일, ZZZ)의 스태미나 정보를 조회합니다.
    비동기 API 호출을 동기 방식으로 래핑하여 GUI 스레드에서 안전하게 사용할 수 있습니다.
    """
    
    GAME_TYPES = {
        "honkai_starrail": {
            "name": "붕괴: 스타레일",
            "stamina_name": "개척력",
        },
        "zenless_zone_zero": {
            "name": "젠레스 존 제로",
            "stamina_name": "배터리",
        },
    }
    
    def __init__(self, config: Optional[HoYoLabConfig] = None):
        """HoYoLabService 초기화
        
        Args:
            config: HoYoLab 인증 정보 설정. None이면 자동으로 로드.
        """
        self._config = config or HoYoLabConfig()
        self._client: Optional["genshin.Client"] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    def is_available(self) -> bool:
        """genshin.py 라이브러리가 사용 가능한지 확인"""
        return GENSHIN_AVAILABLE
    
    def is_configured(self) -> bool:
        """HoYoLab 인증 정보가 설정되어 있는지 확인"""
        return self._config.is_configured()
    
    def _get_client(self) -> Optional["genshin.Client"]:
        """genshin.py 클라이언트 인스턴스 반환 (lazy initialization)"""
        if not GENSHIN_AVAILABLE:
            logger.warning("genshin.py 라이브러리가 설치되지 않았습니다.")
            return None
        
        if self._client is None:
            credentials = self._config.load_credentials()
            if not credentials:
                logger.warning("HoYoLab 인증 정보가 없습니다.")
                return None
            
            cookies = {
                "ltuid_v2": str(credentials.get("ltuid", "")),
                "ltoken_v2": credentials.get("ltoken_v2", ""),
                "ltmid_v2": credentials.get("ltmid_v2", ""),
            }
            
            self._client = genshin.Client(cookies=cookies)
            logger.info("HoYoLab 클라이언트 초기화 완료")
        
        return self._client
    
    def _run_async(self, coro):
        """비동기 코루틴을 동기적으로 실행
        
        GUI 스레드에서 안전하게 비동기 API를 호출하기 위한 래퍼.
        """
        try:
            # 기존 이벤트 루프가 있는지 확인
            try:
                loop = asyncio.get_running_loop()
                # 이미 실행 중인 루프가 있으면 새 스레드에서 실행
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result(timeout=30)
            except RuntimeError:
                # 실행 중인 루프가 없으면 직접 실행
                return asyncio.run(coro)
        except Exception as e:
            logger.error(f"비동기 실행 오류: {e}")
            raise
    
    def get_stamina(self, hoyolab_game_id: str) -> Optional[StaminaInfo]:
        """게임 타입에 따른 스태미나 조회

        Args:
            hoyolab_game_id: HoYoLab 게임 식별자 ("honkai_starrail" 또는 "zenless_zone_zero")

        Returns:
            StaminaInfo 또는 None (조회 실패 시)
        """
        if hoyolab_game_id == "honkai_starrail":
            return self.get_starrail_stamina()
        elif hoyolab_game_id == "zenless_zone_zero":
            return self.get_zzz_stamina()
        else:
            logger.warning(f"지원하지 않는 게임 타입: {hoyolab_game_id}")
            return None
    
    def get_starrail_stamina(self) -> Optional[StaminaInfo]:
        """붕괴: 스타레일 개척력 정보 조회"""
        client = self._get_client()
        if not client:
            return None
        
        try:
            return self._run_async(self._async_get_starrail_stamina(client))
        except Exception as e:
            logger.error(f"스타레일 스태미나 조회 실패: {e}")
            return None
    
    async def _async_get_starrail_stamina(self, client: "genshin.Client") -> Optional[StaminaInfo]:
        """스타레일 스태미나 비동기 조회"""
        try:
            client.game = genshin.Game.STARRAIL
            
            # 설정된 UID가 있으면 사용
            credentials = self._config.load_credentials()
            if credentials and credentials.get("starrail_uid"):
                client.uid = credentials["starrail_uid"]
            
            notes = await client.get_starrail_notes()
            
            now = datetime.now()
            full_time = None
            if notes.stamina_recover_time.total_seconds() > 0:
                full_time = now + notes.stamina_recover_time
            
            return StaminaInfo(
                game_id="honkai_starrail",
                game_name="붕괴: 스타레일",
                current=notes.current_stamina,
                max=notes.max_stamina,
                recover_time=int(notes.stamina_recover_time.total_seconds()),
                full_time=full_time,
                updated_at=now,
            )
        except Exception as e:
            logger.error(f"스타레일 API 호출 실패: {e}")
            return None
    
    def get_zzz_stamina(self) -> Optional[StaminaInfo]:
        """젠레스 존 제로 배터리 정보 조회"""
        client = self._get_client()
        if not client:
            return None
        
        try:
            return self._run_async(self._async_get_zzz_stamina(client))
        except Exception as e:
            logger.error(f"ZZZ 배터리 조회 실패: {e}")
            return None
    
    async def _async_get_zzz_stamina(self, client: "genshin.Client") -> Optional[StaminaInfo]:
        """ZZZ 배터리 비동기 조회"""
        try:
            client.game = genshin.Game.ZZZ
            
            # 설정된 UID가 있으면 사용
            credentials = self._config.load_credentials()
            if credentials and credentials.get("zzz_uid"):
                client.uid = credentials["zzz_uid"]
            
            notes = await client.get_zzz_notes()
            
            now = datetime.now()
            full_time = None
            recover_seconds = getattr(notes.battery_charge, "seconds_till_full", 0)
            if recover_seconds > 0:
                full_time = now + timedelta(seconds=recover_seconds)
            
            return StaminaInfo(
                game_id="zenless_zone_zero",
                game_name="젠레스 존 제로",
                current=notes.battery_charge.current,
                max=notes.battery_charge.max,
                recover_time=recover_seconds,
                full_time=full_time,
                updated_at=now,
            )
        except Exception as e:
            logger.error(f"ZZZ API 호출 실패: {e}")
            return None
    
    def close(self) -> None:
        """클라이언트 연결 종료"""
        if self._client:
            try:
                self._run_async(self._client.close())
            except Exception:
                pass
            self._client = None
            logger.info("HoYoLab 클라이언트 연결 종료")


# 전역 서비스 인스턴스 (싱글톤)
_service_instance: Optional[HoYoLabService] = None


def get_hoyolab_service() -> HoYoLabService:
    """HoYoLabService 싱글톤 인스턴스 반환"""
    global _service_instance
    if _service_instance is None:
        _service_instance = HoYoLabService()
    return _service_instance


def reset_hoyolab_service() -> None:
    """HoYoLabService 인스턴스 리셋 (설정 변경 시 호출)"""
    global _service_instance
    if _service_instance:
        _service_instance.close()
    _service_instance = None
