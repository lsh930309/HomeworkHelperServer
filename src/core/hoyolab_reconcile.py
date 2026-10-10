"""HoYoLab 조회를 직렬 저장하고 각 종료 세션을 독립적으로 보정한다."""
from __future__ import annotations

import logging
import time

from src.core import credential_health
from src.core.provider_activity import provider_activity
from src.core.provider_health_persist import ProviderHealthPersistTask
from src.core.resource_reconcile import _ResourceFollowupCoordinator
from src.data.data_models import ManagedProcess

logger = logging.getLogger(__name__)


def _persist_stamina_observation(job, payload, transport, is_current) -> dict:
    stamina = payload["stamina"]
    fetched_at = payload["fetched_at"]
    result = {"process_row": None, "session_succeeded": False}
    try:
        # 같은 관측값에서 회복 기준을 유지할지는 DB writer가 판단한다.
        result["process_row"] = transport.update_process_stamina(
            job.process_id, stamina.current, stamina.max, fetched_at,
        )
    except Exception as exc:
        result["process_error"] = str(exc)
    if job.session_id is not None and is_current(job):
        recovered = int(max(0.0, fetched_at - job.exit_timestamp) / HoYoStaminaReconcileCoordinator.RECOVERY_RATE_SEC)
        corrected = max(0, min(stamina.current - recovered, stamina.max))
        try:
            transport.update_session_stamina(job.session_id, corrected)
            result["corrected_exit_stamina"] = corrected
            result["session_succeeded"] = True
        except Exception as exc:
            result["session_error"] = str(exc)
    return result


class HoYoStaminaReconcileCoordinator(_ResourceFollowupCoordinator):
    """재실행에 취소되지 않는 HoYoLab 종료별 follow-up을 제공한다."""

    RECOVERY_RATE_SEC = 360

    def _get_service(self):
        from src.services.hoyolab import get_hoyolab_service
        return get_hoyolab_service()

    def _target(self, process):
        return (process.hoyolab_game_id,) if process.is_hoyoverse_game() else None

    def _event_target(self, event):
        return (event.hoyolab_game_id,) if event.is_hoyoverse_game() else None

    def _fetch_observation(self, job):
        service = job.service
        payload = {"stamina": None, "fetched_at": time.time(), "observation_succeeded": False}
        if not service or not service.is_available():
            payload.update(provider_status="unavailable", error="HoYoLab 서비스를 사용할 수 없습니다.")
        elif not service.is_configured():
            payload.update(provider_status="auth_required", error="HoYoLab 인증 정보가 없습니다.")
        else:
            with provider_activity("hoyolab", "stamina_fetch"):
                stamina = service.get_stamina(job.target[0])
            payload["stamina"] = stamina
            if stamina is not None:
                payload.update(fetched_at=stamina.updated_at.timestamp(), provider_status="ok", observation_succeeded=True)
            else:
                payload.update(provider_status="network_error", error="HoYoLab 스태미나 조회에 실패했습니다.")
        return payload

    def _persist_observation(self, job, payload, is_current):
        return _persist_stamina_observation(job, payload, self._transport, is_current)

    def _apply_process_row(self, process, row):
        for key in ("stamina_current", "stamina_max", "stamina_updated_at"):
            setattr(process, key, row[key])

    def _record_observation_health(self, process, payload):
        status = payload.get("provider_status")
        if status:
            self._record_provider_health_from_status(
                process, status, payload.get("error") or "HoYoLab 스태미나 조회 성공", payload["fetched_at"],
            )

    def _record_provider_health_from_status(self, process: ManagedProcess, status: str, message: str, fetched_at: float) -> None:
        payload = credential_health.update_payload_for_reason(
            credential_health.PROVIDER_HOYOLAB, status, message=message, source="stamina_tracking",
            process_id=process.id, game_id=getattr(process, "hoyolab_game_id", None), detected_at=fetched_at,
        )
        if payload is None:
            return
        self._health_pool.start(ProviderHealthPersistTask(self._transport, payload, context="HoYoLab stamina_tracking"))
        if credential_health.is_alertable_health(payload["status"], payload["reason"]):
            self._send_provider_health_notification(process, payload)

    def _send_provider_health_notification(self, process: ManagedProcess, payload: dict[str, object]) -> None:
        if self._notifier is None:
            return
        try:
            self._notifier.send_notification(
                title=f"{process.name} 계정/토큰 확인 필요",
                message=str(payload.get("message") or payload.get("reason") or ""),
                task_id_to_highlight=process.id, button_text="확인", button_action="show",
            )
        except Exception as exc:
            logger.debug("[HoYoLab] provider health 알림 전송 실패: %s", exc, exc_info=True)
