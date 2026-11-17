"""API가 제공자 조회와 현재 자원·종료 세션의 저장 권한을 함께 소유한다."""
from __future__ import annotations

import copy
import logging
import math
import time
from dataclasses import dataclass

from src.utils.resource_tracking import (
    NIKKE_OUTPOST_FULL_CHARGE_SECONDS,
    NIKKE_OUTPOST_LABEL,
    STAMINA_RECOVERY_SECONDS_PER_UNIT,
    clamp_percent,
    is_nikke_outpost_resource,
    is_wuwa_waveplate_resource,
    resource_quantity_percent,
)


FOLLOWUP_WINDOW_SECONDS = 600.0
logger = logging.getLogger(__name__)


def resource_target(process) -> tuple[str, ...] | None:
    if (
        getattr(process, "stamina_tracking_enabled", False)
        and getattr(process, "hoyolab_game_id", None) in {"honkai_starrail", "zenless_zone_zero"}
    ):
        return "hoyolab", process.hoyolab_game_id
    if getattr(process, "resource_tracking_enabled", False):
        provider, key = getattr(process, "resource_provider", None), getattr(process, "resource_key", None)
        if is_wuwa_waveplate_resource(provider, key):
            from src.utils.wuwa_config import WuwaConfig
            account = WuwaConfig().load_selected_resource_key()
            return (provider, key, account) if account is not None else None
        if is_nikke_outpost_resource(provider, key):
            return provider, key
    return None


@dataclass(frozen=True)
class ResourceObservation:
    """실제 요청 시작과 응답을 묶은 API 내부 입력. HTTP에서 역직렬화하지 않는다."""

    process_id: str
    target: tuple[str, ...]
    session_id: int | None
    session_end_timestamp: float | None
    request_started_at: float
    fetched_at: float
    stamina_current: int | None = None
    stamina_max: int | None = None
    resource_percent: float | None = None
    resource_status: str | None = None
    resource_label: str | None = None
    resource_current: int | None = None
    resource_max: int | None = None
    resource_reserve_current: int | None = None
    resource_reserve_max: int | None = None

    def session_values(self, process, session) -> dict:
        """저장 시각 대신 고정 세션과 실제 요청 시작으로만 보정 범위를 판정한다."""
        if (
            self.session_id is None or self.session_end_timestamp is None
            or session is None or session.id != self.session_id
            or session.process_id != self.process_id
            or session.end_timestamp != self.session_end_timestamp
            or getattr(session, "session_status", "closed") != "closed"
            or resource_target(process) != self.target
            or not math.isfinite(self.request_started_at)
            or not math.isfinite(self.fetched_at)
            or not self.session_end_timestamp <= self.request_started_at < self.session_end_timestamp + FOLLOWUP_WINDOW_SECONDS
        ):
            raise ValueError("이 관측은 지정된 종료 세션을 보정할 권한이 없습니다.")
        elapsed = max(0.0, self.fetched_at - self.session_end_timestamp)
        if self.target[0] == "hoyolab":
            if self.stamina_current is None or self.stamina_max is None:
                raise ValueError("관측된 스태미나 값이 없습니다.")
            recovered = int(elapsed / STAMINA_RECOVERY_SECONDS_PER_UNIT)
            return {"stamina_at_end": max(0, min(self.stamina_current - recovered, self.stamina_max))}
        percent = (resource_quantity_percent(self.resource_current, self.resource_max)
                   if self.target[0] == "wuwa" else clamp_percent(self.resource_percent))
        if percent is None:
            raise ValueError("관측된 자원 백분율이 없습니다.")
        if self.target[0] == "wuwa":
            # 명조의 회복 시간 필드는 아직 검증되지 않았으므로 역산하지 않는다.
            return {"resource_percent_at_end": percent}
        return {"resource_percent_at_end": clamp_percent(percent - elapsed * 100.0 / NIKKE_OUTPOST_FULL_CHARGE_SECONDS)}


class _ProviderConfigSnapshot:
    """한 요청의 계정 입력을 고정하고 기존 설정 writer의 자동 갱신만 승계한다."""

    def __init__(self, canonical, provider: str):
        self._canonical = canonical
        self._provider = provider
        self._payload = copy.deepcopy(self._read())
        self._expected = copy.deepcopy(self._payload)

    def _read(self):
        return self._canonical.load_credentials() if self._provider == "hoyolab" else self._canonical.load_session()

    def _same_account(self, current) -> bool:
        expected = self._expected
        if not current or not expected:
            return current == expected
        if self._provider == "hoyolab":
            if not current.get("ltuid") or not current.get("ltoken_v2"):
                return False
            keys = ("ltuid", "starrail_uid", "zzz_uid")
            return all(current.get(key) == expected.get(key) for key in keys)
        if not current.get("cookies"):
            return False
        keys = ("intl_open_id", "nikke_area_id")
        if all(expected.get(key) is not None for key in keys):
            return all(current.get(key) == expected.get(key) for key in keys)
        # 대표 계정을 아직 모르면 쿠키가 그 입력의 유일한 식별 근거다.
        return all(current.get(key) == expected.get(key) for key in keys) and current.get("cookies") == expected.get("cookies")

    def is_current(self) -> bool:
        return self._same_account(self._read())

    def load_credentials(self):
        return copy.deepcopy(self._payload)

    def load_session(self):
        return copy.deepcopy(self._payload)

    def is_configured(self):
        payload = self._payload or {}
        if self._provider == "hoyolab":
            return bool(payload.get("ltuid") and payload.get("ltoken_v2"))
        return bool(payload.get("cookies"))

    def save_session(self, cookies, *, intl_open_id=None, nikke_area_id=None):
        # 자동 쿠키 회전은 계정 전환이 아니다. 도중 수동 교체·삭제된 설정은 덮지 않는다.
        if self._read() != self._expected:
            return False
        saved = self._canonical.save_session(cookies, intl_open_id=intl_open_id, nikke_area_id=nikke_area_id)
        if saved:
            self._payload = copy.deepcopy(self._read())
            self._expected = copy.deepcopy(self._payload)
        return saved

    def update_role(self, *, intl_open_id, nikke_area_id):
        return self.save_session(
            (self._payload or {}).get("cookies") or {},
            intl_open_id=intl_open_id, nikke_area_id=nikke_area_id,
        )


def observe_process_resource(
    process_id: str,
    session_id: int | None = None,
    *,
    session_factory,
    hoyolab_service_factory=None,
    nikke_service_factory=None,
    wuwa_service_factory=None,
    hoyolab_config_factory=None,
    nikke_config_factory=None,
    clock=time.time,
    is_cancelled=lambda: False,
) -> dict:
    """외부 값·시각을 받지 않고 실제 조회와 독립적인 두 저장 결과를 반환한다."""
    from src.core.daily_checkin_singleflight import daily_checkin_singleflight
    from src.core.provider_activity import provider_activity
    from src.data import crud, models, schemas

    result = {"process_row": None, "observation_succeeded": False, "session_succeeded": False, "fetched_at": clock()}

    def read_target():
        with session_factory() as db:
            process = crud.get_process_by_id(db, process_id)
            target = resource_target(process)
            end = None
            if session_id is not None:
                session = db.query(models.ProcessSession).filter(models.ProcessSession.id == session_id).first()
                if session is None or session.process_id != process_id or session.end_timestamp is None or session.session_status != "closed":
                    raise ValueError("지정한 게임의 정상 종료 세션이 아닙니다.")
                end = float(session.end_timestamp)
            if target is None:
                raise ValueError("지원되는 자원 추적 게임이 아닙니다.")
            return target, end

    try:
        target, exit_timestamp = read_target()
    except ValueError as exc:
        result.update(cancelled=True, error=str(exc))
        return result

    # GUI 외 직접 호출도 기존 single-flight 안에서 조회와 저장을 하나로 완료한다.
    lease = daily_checkin_singleflight.try_acquire("resource-observation", target[0], "", "", 0.0)
    if lease is None:
        result.update(provider_status="busy", error="같은 제공자의 자원 관측이 진행 중입니다.")
        return result
    with lease, provider_activity(target[0], "resource_observation"):
        if target[0] == "hoyolab":
            if hoyolab_config_factory is None:
                from src.utils.hoyolab_config import HoYoLabConfig
                hoyolab_config_factory = HoYoLabConfig
            if hoyolab_service_factory is None:
                from src.services.hoyolab import HoYoLabService
                hoyolab_service_factory = HoYoLabService
            config = _ProviderConfigSnapshot(hoyolab_config_factory(), target[0])
            service = hoyolab_service_factory(config)
        elif target[0] == "wuwa":
            if wuwa_service_factory is None:
                from src.services.wuwa import WuwaService
                wuwa_service_factory = WuwaService
            service = wuwa_service_factory()
            config = service
        else:
            if nikke_config_factory is None:
                from src.utils.nikke_config import NikkeConfig
                nikke_config_factory = NikkeConfig
            if nikke_service_factory is None:
                from src.services.nikke import NikkeService
                nikke_service_factory = NikkeService
            config = _ProviderConfigSnapshot(nikke_config_factory(), target[0])
            service = nikke_service_factory(config)

        request_started_at = None

        def require_current(*, starting=False):
            nonlocal request_started_at
            try:
                current_target = read_target()
            except ValueError:
                current_target = None
            if is_cancelled() or not config.is_current() or current_target != (target, exit_timestamp):
                result.update(cancelled=True, error="게임·제공자·계정 또는 앱 수명주기가 변경되어 관측을 취소했습니다.")
                raise RuntimeError(result["error"])
            if starting:
                started = float(clock())
                if exit_timestamp is not None and not exit_timestamp <= started < exit_timestamp + FOLLOWUP_WINDOW_SECONDS:
                    result.update(expired=True, error="종료 후 10분 관측 기간이 끝났습니다.")
                    raise RuntimeError(result["error"])
                request_started_at = started

        try:
            require_current()
            if exit_timestamp is not None and not exit_timestamp <= clock() < exit_timestamp + FOLLOWUP_WINDOW_SECONDS:
                result.update(expired=True, error="종료 후 10분 관측 기간이 끝났습니다.")
                return result
            if not config.is_configured():
                result.update(provider_status="auth_required", error="제공자 인증 정보가 없습니다.")
                return result
            if target[0] == "hoyolab":
                if not service.is_available():
                    result.update(provider_status="unavailable", error="HoYoLab 서비스를 사용할 수 없습니다.")
                    return result
                stamina = service.get_stamina(target[1], before_fetch=lambda: require_current(starting=True))
                if stamina is None:
                    if not result.get("expired") and not result.get("cancelled"):
                        result.update(provider_status="network_error", error="HoYoLab 스태미나 조회에 실패했습니다.")
                    return result
                fetched_at = stamina.updated_at.timestamp()
                values = dict(stamina_current=int(stamina.current), stamina_max=int(stamina.max))
                values.update(resource_reserve_current=getattr(stamina, "reserve_current", None),
                              resource_reserve_max=getattr(stamina, "reserve_max", None))
                result["provider_status"] = "ok"
            elif target[0] == "wuwa":
                snapshot = service.get_resource_snapshot(
                    target[1], before_fetch=lambda: require_current(starting=True),
                    before_prepare=lambda: require_current(),
                )
                if result.get("expired") or result.get("cancelled"):
                    return result
                require_current()
                result.update(provider_status=snapshot.status, error=snapshot.message or None, fetched_at=snapshot.updated_at.timestamp())
                if snapshot.status != "ok":
                    return result
                fetched_at = snapshot.updated_at.timestamp()
                values = dict(resource_percent=None, resource_status="ok", resource_current=snapshot.current,
                              resource_max=snapshot.maximum, resource_reserve_current=snapshot.reserve_current,
                              resource_reserve_max=snapshot.reserve_max)
            else:
                snapshot = service.get_outpost_storage(before_fetch=lambda: require_current(starting=True))
                if result.get("expired") or result.get("cancelled"):
                    return result
                result.update(provider_status=snapshot.status, error=snapshot.message or None, fetched_at=snapshot.updated_at.timestamp())
                if snapshot.status != "ok" or snapshot.percent is None:
                    return result
                fetched_at = snapshot.updated_at.timestamp()
                values = dict(resource_percent=clamp_percent(snapshot.percent), resource_status=snapshot.status, resource_label=snapshot.label or NIKKE_OUTPOST_LABEL)
                if values["resource_percent"] is None:
                    result.update(provider_status="unavailable", error="제공자가 유효한 자원 백분율을 반환하지 않았습니다.")
                    return result
            require_current()
            if request_started_at is None:
                raise RuntimeError("제공자가 실제 자원 요청 시작을 확인하지 않았습니다.")
            if not math.isfinite(fetched_at):
                raise ValueError("제공자의 관측 시각이 유효하지 않습니다.")
            observation = ResourceObservation(process_id, target, session_id, exit_timestamp, request_started_at, fetched_at, **values)
            result.update(observation_succeeded=True, fetched_at=fetched_at)
            try:
                with session_factory() as db:
                    require_current()
                    if target[0] == "hoyolab":
                        row = crud.update_process_stamina(db, process_id, stamina_updated_at=fetched_at, **values)
                    else:
                        row = crud.update_process_resource(db, process_id, resource_updated_at=fetched_at, **values)
                    if row is None:
                        raise ValueError("저장할 게임이 삭제되었습니다.")
                    result["process_row"] = schemas.ProcessSchema.model_validate(row).model_dump()
            except Exception as exc:
                result["process_error"] = str(exc)
            if session_id is not None:
                try:
                    with session_factory() as db:
                        require_current()
                        corrected = crud.apply_session_resource_observation(db, observation)
                        result["session_succeeded"] = True
                        result.update({"corrected_exit_stamina" if key == "stamina_at_end" else "corrected_exit_percent": value for key, value in corrected.items()})
                except Exception as exc:
                    result["session_error"] = str(exc)
            return result
        except Exception as exc:
            if not result.get("error"):
                result["error"] = str(exc)
            return result
        finally:
            closer = getattr(service, "close", None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    # 정리 실패가 완료된 독립 저장 결과를 뒤집지는 않는다.
                    logger.warning("자원 관측 서비스 정리에 실패했습니다.", exc_info=True)
