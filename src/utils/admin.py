"""The user application stays unelevated; privileged work belongs to SCM."""
import ctypes
import os


def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def privilege_service_status() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "Windows 권한 서비스는 Windows 호스트에서 사용합니다."
    from src.host_service.client import HostPrivilegeClient, PrivilegeServiceError, PrivilegeServiceUnavailable
    try:
        response = HostPrivilegeClient().status()
        ready = bool(response.get("accepted"))
        return ready, str(response.get("message") or ("권한 서비스 준비됨" if ready else "권한 서비스 준비 안 됨"))
    except (PrivilegeServiceError, PrivilegeServiceUnavailable) as exc:
        return False, f"권한 서비스가 준비되지 않았습니다. 설치 패키지를 설치해 주세요. ({exc})"


def check_admin_requirement() -> bool:
    """Fail before user data initialization when manually launched elevated."""
    if is_admin():
        raise RuntimeError("HomeworkHelper는 일반 사용자 권한으로 실행해야 합니다. 관리자 실행을 해제해 주세요. 관리자 기능은 설치된 권한 서비스가 처리합니다.")
    return False
