"""SCM idempotency contracts; Windows uses the real pywintypes exception class.

All service API effects are inert. These tests never register, stop or remove a service.
"""

import os
import sys
from types import SimpleNamespace

import pytest

import homework_helper_service as entry
from src.host_service import windows_backend as native


@pytest.fixture
def registration(monkeypatch):
    if os.name == "nt":
        import pywintypes
        error_type = pywintypes.error
    else:
        # Deliberately not an OSError: exercise the same catch boundary on other platforms.
        class PyWinError(Exception):
            def __init__(self, winerror, function, message):
                super().__init__(winerror, function, message)
                self.winerror = winerror
        error_type = PyWinError
        monkeypatch.setitem(sys.modules, "pywintypes", SimpleNamespace(error=error_type))

    effects = []
    service = SimpleNamespace(
        SERVICE_STOPPED=1, SERVICE_STOP_PENDING=3, SERVICE_AUTO_START=2,
        SC_MANAGER_CONNECT=1, SERVICE_CHANGE_CONFIG=2, SERVICE_CONFIG_FAILURE_ACTIONS=2,
        SC_ACTION_RESTART=1, SC_ACTION_NONE=0, SERVICE_RUNNING=4,
        OpenSCManager=lambda *_args: "manager",
        OpenService=lambda *_args: "service",
        ChangeServiceConfig2=lambda *_args: effects.append("recovery"),
        CloseServiceHandle=lambda handle: effects.append(("close", handle)),
    )
    service_util = SimpleNamespace(
        QueryServiceStatus=lambda _name: (0, service.SERVICE_STOPPED),
        StopService=lambda _name: effects.append("stop"),
        InstallService=lambda *_args, **_kwargs: effects.append("install"),
        ChangeServiceConfig=lambda *_args, **_kwargs: effects.append("update"),
        StartService=lambda _name: effects.append("start"),
        WaitForServiceStatus=lambda *_args: effects.append("wait-running"),
        RemoveService=lambda _name: effects.append("remove"),
    )
    monkeypatch.setitem(sys.modules, "win32service", service)
    monkeypatch.setitem(sys.modules, "win32serviceutil", service_util)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry, "service_class", lambda: SimpleNamespace(_svc_description_="service"))
    monkeypatch.setattr(native, "validate_protected_install", lambda _path: effects.append("validate"))
    monkeypatch.setattr(native, "write_owner_sid", lambda _owner: effects.append("owner-written"))
    monkeypatch.setattr(native, "remove_owner_sid", lambda: effects.append("owner-removed"))
    return SimpleNamespace(error=error_type, service=service, util=service_util, effects=effects)


def raises(error):
    def call(*_args, **_kwargs):
        raise error
    return call


def test_stop_missing_service_accepts_native_1060(registration):
    error = registration.error(1060, "GetServiceKeyName", "service does not exist")
    registration.util.QueryServiceStatus = raises(error)
    entry.stop_service()
    assert registration.effects == []


@pytest.mark.parametrize("code", [5, 1073, 1722])
def test_stop_propagates_other_native_errors(registration, code):
    error = registration.error(code, "QueryServiceStatus", "native failure")
    registration.util.QueryServiceStatus = raises(error)
    with pytest.raises(registration.error) as caught:
        entry.stop_service()
    assert caught.value is error and registration.effects == []


def test_stop_does_not_hide_non_pywin32_error_with_same_number(registration):
    error = OSError(1060, "unexpected filesystem or Python failure")
    error.winerror = 1060
    registration.util.QueryServiceStatus = raises(error)
    with pytest.raises(OSError) as caught:
        entry.stop_service()
    assert caught.value is error


def test_stop_service_removed_during_stop_is_idempotent(registration):
    registration.util.QueryServiceStatus = lambda _name: (0, registration.service.SERVICE_RUNNING)
    registration.util.StopService = raises(registration.error(1060, "StopService", "already removed"))
    entry.stop_service()
    assert registration.effects == []


def test_first_install_continues_after_missing_service_stop(registration):
    registration.util.QueryServiceStatus = raises(registration.error(1060, "GetServiceKeyName", "missing"))
    entry.install_service("owner")
    assert "install" in registration.effects and "update" not in registration.effects
    assert "owner-written" in registration.effects and "wait-running" in registration.effects
    assert ("close", "service") in registration.effects and ("close", "manager") in registration.effects


def test_existing_install_updates_config_only_for_native_1073(registration):
    registration.util.InstallService = raises(registration.error(1073, "CreateService", "already exists"))
    entry.install_service("owner")
    assert registration.effects.count("update") == 1
    assert registration.effects.index("update") < registration.effects.index("owner-written")
    assert "wait-running" in registration.effects


@pytest.mark.parametrize("code", [5, 1060, 1722])
def test_install_propagates_other_native_errors_before_owner_and_start(registration, code):
    error = registration.error(code, "CreateService", "native failure")
    registration.util.InstallService = raises(error)
    with pytest.raises(registration.error) as caught:
        entry.install_service("owner")
    assert caught.value is error
    assert "update" not in registration.effects
    assert "owner-written" not in registration.effects and "start" not in registration.effects


def test_install_does_not_hide_non_pywin32_error_with_same_number(registration):
    error = OSError(1073, "unexpected non-SCM failure")
    error.winerror = 1073
    registration.util.InstallService = raises(error)
    with pytest.raises(OSError) as caught:
        entry.install_service("owner")
    assert caught.value is error and "update" not in registration.effects


def test_existing_config_update_failure_is_propagated(registration):
    registration.util.InstallService = raises(registration.error(1073, "CreateService", "already exists"))
    error = registration.error(5, "ChangeServiceConfig", "access denied")
    registration.util.ChangeServiceConfig = raises(error)
    with pytest.raises(registration.error) as caught:
        entry.install_service("owner")
    assert caught.value is error and "owner-written" not in registration.effects


def test_uninstall_already_removed_service_accepts_native_1060(registration):
    registration.util.QueryServiceStatus = raises(registration.error(1060, "GetServiceKeyName", "missing"))
    registration.util.RemoveService = raises(registration.error(1060, "OpenService", "already removed"))
    entry.uninstall_service()
    assert registration.effects == ["owner-removed"]


@pytest.mark.parametrize("code", [5, 1073, 1722])
def test_uninstall_propagates_other_native_errors(registration, code):
    error = registration.error(code, "DeleteService", "native failure")
    registration.util.RemoveService = raises(error)
    with pytest.raises(registration.error) as caught:
        entry.uninstall_service()
    assert caught.value is error


def test_uninstall_does_not_hide_non_pywin32_error_with_same_number(registration):
    error = OSError(1060, "unexpected non-SCM failure")
    error.winerror = 1060
    registration.util.RemoveService = raises(error)
    with pytest.raises(OSError) as caught:
        entry.uninstall_service()
    assert caught.value is error


@pytest.mark.skipif(os.name != "nt", reason="Requires actual pywin32 exception class")
def test_actual_windows_pywin32_error_is_not_an_oserror():
    import pywintypes
    error = pywintypes.error(1060, "GetServiceKeyName", "service does not exist")
    assert error.winerror == 1060 and not isinstance(error, OSError)
