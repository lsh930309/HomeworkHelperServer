"""Local callers address registered IDs, never privileged arbitrary paths."""

from __future__ import annotations

from .constants import PIPE_NAME


class PrivilegeServiceError(RuntimeError):
    """The service rejected a request or returned an invalid reply."""

    def __init__(self, message, *, status="error"):
        super().__init__(message)
        self.status = status


class PrivilegeServiceUnavailable(PrivilegeServiceError):
    """Service registration, connection or response is unavailable."""


class HostPrivilegeClient:
    def __init__(self, *, transport=None, before_ack=None):
        self._transport = transport
        self._before_ack = before_ack

    def _request(self, operation: str, **values) -> dict:
        transport = self._transport
        if transport is None:
            from .transport import pipe_request
            transport = lambda request: pipe_request(request, before_ack=self._before_ack)
        try:
            response = transport({"operation":operation, **values})
        except PrivilegeServiceError:
            raise
        except (OSError, TimeoutError, RuntimeError) as error:
            raise PrivilegeServiceUnavailable("권한 서비스에 연결할 수 없습니다. 설치 상태를 확인해 주세요.") from error
        except (ValueError, TypeError) as error:
            raise PrivilegeServiceError("권한 서비스 응답 형식이 올바르지 않습니다.") from error
        if not isinstance(response, dict) or type(response.get("accepted")) is not bool:
            raise PrivilegeServiceError("권한 서비스 응답 형식이 올바르지 않습니다.")
        if not response["accepted"]:
            raise PrivilegeServiceError(str(response.get("message") or "권한 요청이 거부되었습니다."),
                                        status=str(response.get("status") or "denied"))
        return response

    def status(self) -> dict:
        return self._request("status")

    def launch_managed(self, process_id: str, mode: str = "auto") -> dict:
        return self._request("launch_managed", process_id=process_id, mode=mode)

    def inspect_managed(self, process_ids) -> dict:
        return self._request("inspect_managed", process_ids=list(process_ids))

    def stop_managed(self, process_id: str, *, pid=None, create_time=None) -> dict:
        request = {"process_id":process_id}
        if pid is not None:
            request.update(pid=pid, create_time=create_time)
        elif create_time is not None:
            request["create_time"] = create_time
        return self._request("stop_managed", **request)

    def control_power(self, action: str) -> dict:
        return self._request("power", action=action)
