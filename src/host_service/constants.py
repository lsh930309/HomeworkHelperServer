"""Installed service identity; no per-user runtime data is stored here."""

SERVICE_NAME = "HomeworkHelperPrivilege"
SERVICE_DISPLAY_NAME = "HomeworkHelper privilege service"
SERVICE_EXE = "homework_helper_service.exe"
APP_EXE = "homework_helper.exe"
PIPE_NAME = r"\\.\pipe\HomeworkHelperPrivilege"
REGISTRY_PARAMETERS = rf"SYSTEM\CurrentControlSet\Services\{SERVICE_NAME}\Parameters"
MAX_MESSAGE_BYTES = 65536
IPC_TIMEOUT_MS = 5000
SYSTEM_SID = "S-1-5-18"
