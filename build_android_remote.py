#!/usr/bin/env python3
"""Build the Android Remote client, archive the APK, and install over wireless adb.

The phone-side prerequisites remain intentionally manual: an adb-reachable
network path, Wireless debugging, and first-time pairing-code consent must be
enabled on the device. Tailscale can still provide that adb path, but the APK
itself is built as a lightweight direct-connection client. This script automates
the host-side deterministic parts: signed release Gradle build, release APK
naming/archiving, adb pair/connect, and adb install.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import build
from src.core.tailscale import TailscalePeer, TailscaleSnapshot, tailscale_status


PROJECT_ROOT = Path(__file__).resolve().parent
ANDROID_ROOT = PROJECT_ROOT / "remote_clients" / "android" / "HomeworkHelperRemote"
DEFAULT_APK = ANDROID_ROOT / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
DEFAULT_JAVA_HOME = "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
DEFAULT_ANDROID_HOME = "/opt/homebrew/share/android-commandlinetools"
DEFAULT_ADB = "/opt/homebrew/share/android-commandlinetools/platform-tools/adb"
DEFAULT_SANDBOX_HOME = Path("/private/tmp/homeworkhelper-android-build-home")
DEFAULT_GRADLE_HOME = Path("/private/tmp/homeworkhelper-android-build-gradle")
DEFAULT_ANDROID_USER_HOME = Path("/private/tmp/homeworkhelper-android-build-user")
DEFAULT_DEBUG_KEYSTORE = PROJECT_ROOT / "local-artifacts" / "android-signing" / "homeworkhelper-android-debug.keystore"
DEBUG_KEYSTORE_PASSWORD = "android"
DEBUG_KEY_ALIAS = "androiddebugkey"

ANDROID_TARGET = "android-client"
APK_PREFIX = "HomeworkHelperRemoteAndroid"
DEFAULT_ANDROID_VERSION = {"version": "0.1.0", "build": 1}
ANDROID_VERSION_CODE_LIMIT = 2_100_000_000
ADB_TLS_PAIRING_SERVICE = "_adb-tls-pairing._tcp"
ADB_TLS_CONNECT_SERVICE = "_adb-tls-connect._tcp"
PACKAGE_NAME = "dev.homeworkhelper.remote"
MAIN_ACTIVITY = f"{PACKAGE_NAME}/.MainActivity"
REMOTE_AGENT_DEFAULT_SCHEME = "http"
REMOTE_AGENT_DEFAULT_PORT = 8000
REMOTE_AGENT_BASE_URL_GRADLE_PROPERTY = "homeworkhelper.android.defaultRemoteBaseUrl"
_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")
PUBLIC_REMOTE_AGENT_DEFAULT_SCHEME = "https"
PUBLIC_IP_DNS_SUFFIX = "sslip.io"


@dataclass(frozen=True)
class MdnsService:
    name: str
    service_type: str
    host: str
    port: int


def _run(
    command: list[str],
    *,
    cwd: Path = PROJECT_ROOT,
    env: dict[str, str] | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=False,
    )
    if check and completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}")
    return completed


def build_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("JAVA_HOME", DEFAULT_JAVA_HOME)
    env.setdefault("ANDROID_HOME", DEFAULT_ANDROID_HOME)
    env.setdefault("ANDROID_SDK_ROOT", env["ANDROID_HOME"])
    DEFAULT_SANDBOX_HOME.mkdir(parents=True, exist_ok=True)
    DEFAULT_GRADLE_HOME.mkdir(parents=True, exist_ok=True)
    DEFAULT_ANDROID_USER_HOME.mkdir(parents=True, exist_ok=True)
    env.setdefault("GRADLE_USER_HOME", str(DEFAULT_GRADLE_HOME))
    env.setdefault("ANDROID_USER_HOME", str(DEFAULT_ANDROID_USER_HOME))
    gradle_opts = env.get("GRADLE_OPTS", "")
    for option in [
        f"-Duser.home={DEFAULT_SANDBOX_HOME}",
        "-Dkotlin.daemon.enabled=false",
    ]:
        if option not in gradle_opts:
            gradle_opts = f"{gradle_opts} {option}".strip()
    env["GRADLE_OPTS"] = gradle_opts
    return env


def with_android_target(config: dict) -> tuple[dict, bool]:
    updated = build.clone_version_config(config)
    targets = updated.setdefault("targets", {})
    inserted = ANDROID_TARGET not in targets
    if inserted:
        targets[ANDROID_TARGET] = DEFAULT_ANDROID_VERSION.copy()
    return updated, inserted


def candidate_android_version_config(config: dict, bump: str) -> dict:
    seeded, inserted = with_android_target(config)
    if inserted and bump == build.DEFAULT_VERSION_BUMP:
        return seeded
    return build.bump_target_version_config(seeded, ANDROID_TARGET, bump)


def android_version_code(version_info: dict) -> int:
    major = int(version_info["major"])
    minor = int(version_info["minor"])
    patch = int(version_info["patch"])
    build_number = int(version_info["build"])
    if minor >= 100 or patch >= 100 or build_number >= 10_000:
        raise build.BuildConfigError(
            "android-client versionCode 계산 범위를 초과했습니다 "
            "(minor/patch < 100, build < 10000 필요)."
        )
    version_code = major * 100_000_000 + minor * 1_000_000 + patch * 10_000 + build_number
    if version_code < 1 or version_code > ANDROID_VERSION_CODE_LIMIT:
        raise build.BuildConfigError(f"android-client versionCode 범위를 벗어났습니다: {version_code}")
    return version_code


def android_release_apk_path(version_info: dict) -> Path:
    return build.RELEASE_DIR / build.release_filename(APK_PREFIX, version_info, "", "apk")


def normalize_remote_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    if not candidate:
        return ""
    if not _URL_SCHEME_RE.match(candidate):
        host_candidate = candidate.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
        if is_public_ipv4_literal(host_candidate):
            return f"{PUBLIC_REMOTE_AGENT_DEFAULT_SCHEME}://{host_candidate.replace('.', '-')}.{PUBLIC_IP_DNS_SUFFIX}"
        candidate = f"{REMOTE_AGENT_DEFAULT_SCHEME}://{candidate}"

    parsed = urlsplit(candidate)
    if not parsed.scheme or not parsed.netloc:
        return candidate

    try:
        has_port = parsed.port is not None
    except ValueError:
        has_port = ":" in parsed.netloc.rsplit("@", 1)[-1]
    if has_port:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query)).rstrip("/")

    if parsed.scheme.lower() == "https":
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query)).rstrip("/")

    netloc = parsed.netloc
    host_part = netloc.rsplit("@", 1)[-1]
    if ":" in host_part and not host_part.startswith("["):
        prefix = netloc[: -len(host_part)]
        netloc = f"{prefix}[{host_part}]:{REMOTE_AGENT_DEFAULT_PORT}"
    else:
        netloc = f"{netloc}:{REMOTE_AGENT_DEFAULT_PORT}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", parsed.query)).rstrip("/")


def is_private_remote_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized in {"localhost", "testclient"} or normalized.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address in _TAILSCALE_CGNAT
    )


def is_public_ipv4_literal(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host.strip())
    except ValueError:
        return False
    return bool(address.version == 4 and address.is_global)


def public_cleartext_remote_base_url(value: str) -> bool:
    normalized = normalize_remote_base_url(value)
    if not normalized:
        return False
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != "http":
        return False
    return not is_private_remote_host(parsed.hostname or "")


def validate_remote_base_url_for_android(value: str) -> str:
    normalized = normalize_remote_base_url(value)
    if public_cleartext_remote_base_url(normalized):
        raise RuntimeError(
            "Android public 직접접속 URL은 HTTPS여야 합니다. "
            f"public HTTP URL은 APK 기본값으로 주입할 수 없습니다: {normalized}"
        )
    return normalized


def create_gradle_assemble_command(
    version_info: dict,
    *,
    debug_keystore: Path = DEFAULT_DEBUG_KEYSTORE,
    default_remote_base_url: str = "",
) -> list[str]:
    command = [
        "./gradlew",
        ":app:assembleRelease",
        "--stacktrace",
        f"-Phomeworkhelper.android.versionName={version_info['version']}",
        f"-Phomeworkhelper.android.versionCode={android_version_code(version_info)}",
        f"-Phomeworkhelper.android.debugStoreFile={debug_keystore}",
        f"-Phomeworkhelper.android.debugStorePassword={DEBUG_KEYSTORE_PASSWORD}",
        f"-Phomeworkhelper.android.debugKeyAlias={DEBUG_KEY_ALIAS}",
        f"-Phomeworkhelper.android.debugKeyPassword={DEBUG_KEYSTORE_PASSWORD}",
    ]
    normalized_base_url = validate_remote_base_url_for_android(default_remote_base_url)
    if normalized_base_url:
        command.append(f"-P{REMOTE_AGENT_BASE_URL_GRADLE_PROPERTY}={normalized_base_url}")
    return command


def keytool_path() -> str:
    java_home = os.environ.get("JAVA_HOME") or DEFAULT_JAVA_HOME
    java_keytool = Path(java_home) / "bin" / "keytool"
    if java_keytool.exists():
        return str(java_keytool)
    found = shutil.which("keytool")
    if found:
        return found
    raise RuntimeError("keytool을 찾을 수 없습니다. JAVA_HOME 또는 PATH를 확인하세요.")


def ensure_debug_keystore(path: Path = DEFAULT_DEBUG_KEYSTORE) -> Path:
    """Create the stable local debug keystore used by Android release-helper builds."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            keytool_path(),
            "-genkeypair",
            "-v",
            "-keystore",
            str(path),
            "-storepass",
            DEBUG_KEYSTORE_PASSWORD,
            "-keypass",
            DEBUG_KEYSTORE_PASSWORD,
            "-alias",
            DEBUG_KEY_ALIAS,
            "-keyalg",
            "RSA",
            "-keysize",
            "2048",
            "-validity",
            "10000",
            "-dname",
            "CN=Android Debug,O=Android,C=US",
            "-noprompt",
        ],
        env=build_environment(),
    )
    return path


def ensure_release_dir() -> None:
    build.RELEASE_DIR.mkdir(parents=True, exist_ok=True)


def prune_archives_for_targets(targets: set[str], *, keep: int, days: int) -> int:
    if keep < 1:
        keep = 1
    if not build.ARCHIVES_DIR.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=max(1, days))
    deleted = 0
    for target in targets:
        target_dir = build.ARCHIVES_DIR / target
        if not target_dir.exists():
            continue
        for bucket_dir in sorted(target_dir.glob("*")):
            if not bucket_dir.is_dir():
                continue
            archived_files = sorted(
                [path for path in bucket_dir.glob("*/*") if path.is_file()],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for index, file_path in enumerate(archived_files):
                if index >= keep or datetime.fromtimestamp(file_path.stat().st_mtime) < cutoff:
                    file_path.unlink()
                    deleted += 1

    for folder in sorted(build.ARCHIVES_DIR.rglob("*"), key=lambda path: len(path.parts), reverse=True):
        if folder.is_dir():
            try:
                next(folder.iterdir())
            except StopIteration:
                folder.rmdir()
            except Exception:
                pass
    return deleted


def archive_release_artifacts(
    *,
    targets: set[str] | None = None,
    archive_keep: int,
    archive_days: int,
    prune_archives: bool,
) -> list[Path]:
    targets = targets or {ANDROID_TARGET}
    ensure_release_dir()
    date_folder = datetime.now().strftime("%y-%m-%d")
    archived: list[Path] = []
    for file_path in build.iter_release_artifacts_for_archive():
        bucket = build.artifact_archive_bucket(file_path)
        if bucket is None:
            continue
        target, artifact_type = bucket
        if target not in targets:
            continue
        archive_subdir = build.ARCHIVES_DIR / target / artifact_type / date_folder
        archive_subdir.mkdir(parents=True, exist_ok=True)
        dest = archive_subdir / file_path.name
        shutil.move(str(file_path), str(dest))
        archived.append(dest)
        print(f"  ✓ {file_path.name} → {dest.relative_to(build.RELEASE_DIR)}")
    if prune_archives:
        deleted = prune_archives_for_targets(targets, keep=archive_keep, days=archive_days)
        if deleted:
            print(f"  ✓ 오래된 Android archive {deleted}개 정리 완료")
    return archived


def build_android_apk(version_info: dict, *, default_remote_base_url: str = "") -> None:
    readiness = [sys.executable, "tools/check_android_sdk_readiness.py"]
    _run(readiness, env=build_environment())
    debug_keystore = ensure_debug_keystore()
    print(f"  ✓ local signing keystore: {debug_keystore}")
    _run(
        create_gradle_assemble_command(
            version_info,
            debug_keystore=debug_keystore,
            default_remote_base_url=default_remote_base_url,
        ),
        cwd=ANDROID_ROOT,
        env=build_environment(),
    )
    if not DEFAULT_APK.exists():
        raise RuntimeError(f"Gradle build completed but APK was not found: {DEFAULT_APK}")


def copy_release_apk(version_info: dict) -> Path:
    ensure_release_dir()
    release_apk = android_release_apk_path(version_info)
    if release_apk.exists():
        release_apk.unlink()
    shutil.copy2(DEFAULT_APK, release_apk)
    print(f"  ✓ APK release copy: {release_apk}")
    return release_apk


def check_release_apk(release_apk: Path, version_info: dict) -> None:
    _run(
        [
            sys.executable,
            "tools/check_android_apk_artifact.py",
            "--apk",
            str(release_apk),
            "--expected-version-name",
            version_info["version"],
            "--expected-version-code",
            str(android_version_code(version_info)),
        ],
        env=build_environment(),
    )


def resolve_adb(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("adb")
    if found:
        return found
    return DEFAULT_ADB


def find_android_build_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    sdk_root = Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or DEFAULT_ANDROID_HOME)
    build_tools = sdk_root / "build-tools"
    if not build_tools.exists():
        return None
    candidates = sorted(build_tools.glob(f"*/{name}"), reverse=True)
    return str(candidates[0]) if candidates else None


def normalize_cert_digest(value: str) -> str:
    return value.replace(":", "").strip().lower()


def apk_certificate_sha256(apk: Path) -> str:
    apksigner = find_android_build_tool("apksigner")
    if not apksigner:
        raise RuntimeError("apksigner를 찾을 수 없어 APK 서명 preflight를 수행할 수 없습니다.")
    result = _run([apksigner, "verify", "--print-certs", str(apk)], env=build_environment(), capture=True)
    match = re.search(r"certificate SHA-256 digest:\s*([0-9A-Fa-f:]+)", result.stdout or "")
    if not match:
        raise RuntimeError(f"APK signing certificate SHA-256을 읽지 못했습니다: {apk}")
    return normalize_cert_digest(match.group(1))


def installed_package_apk_path(adb: str, serial: str, package_name: str = PACKAGE_NAME) -> str | None:
    result = _run([adb, "-s", serial, "shell", "pm", "path", package_name], capture=True, check=False)
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        line = line.strip().removesuffix("\r")
        if line.startswith("package:"):
            return line.removeprefix("package:")
    return None


def _serial_slug(serial: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", serial)


def pull_installed_apk(adb: str, serial: str, remote_path: str, package_name: str = PACKAGE_NAME) -> Path:
    local_path = Path("/private/tmp") / f"homeworkhelper-installed-{package_name}-{_serial_slug(serial)}.apk"
    _run([adb, "-s", serial, "pull", remote_path, str(local_path)], capture=True)
    return local_path


def installed_apk_certificate_sha256(adb: str, serial: str, package_name: str = PACKAGE_NAME) -> str | None:
    remote_path = installed_package_apk_path(adb, serial, package_name)
    if not remote_path:
        return None
    local_path = pull_installed_apk(adb, serial, remote_path, package_name)
    return apk_certificate_sha256(local_path)


def preflight_install_signature(
    adb: str,
    serial: str,
    apk: Path,
    *,
    uninstall_on_signature_mismatch: bool = False,
) -> str:
    """Return install preflight status and optionally uninstall on a cert mismatch."""
    installed_digest = installed_apk_certificate_sha256(adb, serial)
    if not installed_digest:
        print("  (기존 설치 앱 없음: 서명 preflight 통과)")
        return "not_installed"

    candidate_digest = apk_certificate_sha256(apk)
    if installed_digest == candidate_digest:
        print(f"  ✓ installed APK signature matches: {candidate_digest}")
        return "match"

    message = (
        "기존 설치 앱과 새 APK의 서명이 다릅니다.\n"
        f"- installed: {installed_digest}\n"
        f"- candidate: {candidate_digest}\n"
        "앱 데이터를 보존하려면 같은 keystore로 다시 빌드해야 합니다. "
        "데이터 삭제를 감수하고 전환하려면 --uninstall-on-signature-mismatch를 사용하세요."
    )
    if not uninstall_on_signature_mismatch:
        raise RuntimeError(message)

    print("  ⚠ signature mismatch 감지: 명시 옵션에 따라 기존 앱을 uninstall합니다.")
    print(f"  installed: {installed_digest}")
    print(f"  candidate: {candidate_digest}")
    _run([adb, "-s", serial, "uninstall", PACKAGE_NAME])
    return "uninstalled"


_MDNS_ENDPOINT_RE = re.compile(r"^(?P<host>\[[^\]]+\]|[^:]+):(?P<port>\d+)$")


def parse_adb_mdns_services(output: str) -> list[MdnsService]:
    services: list[MdnsService] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of discovered"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        endpoint = parts[-1]
        match = _MDNS_ENDPOINT_RE.match(endpoint)
        if not match:
            continue
        host = match.group("host").strip("[]")
        services.append(
            MdnsService(
                name=" ".join(parts[:-2]),
                service_type=parts[-2],
                host=host,
                port=int(match.group("port")),
            )
        )
    return services


def discover_mdns_services(adb: str) -> list[MdnsService]:
    _run([adb, "mdns", "check"], capture=True, check=False)
    result = _run([adb, "mdns", "services"], capture=True, check=False)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        return []
    return parse_adb_mdns_services(result.stdout or "")


def choose_mdns_port(services: list[MdnsService], service_type: str, device_ip: str) -> int | None:
    candidates = [service for service in services if service.service_type == service_type]
    exact = [service for service in candidates if service.host == device_ip]
    if len(exact) == 1:
        return exact[0].port
    if not exact and len(candidates) == 1:
        return candidates[0].port
    return None


def _normalized_tailscale_name(value: str) -> str:
    return value.strip().strip(".").lower()


def tailscale_peer_match_score(peer: TailscalePeer, selector: str) -> int:
    normalized_selector = _normalized_tailscale_name(selector)
    if not normalized_selector:
        return 0
    dns_name = _normalized_tailscale_name(peer.dns_name)
    exact_tokens = {
        _normalized_tailscale_name(peer.hostname),
        dns_name,
        dns_name.split(".", 1)[0] if dns_name else "",
        _normalized_tailscale_name(peer.node_id),
        peer.primary_ipv4(),
    }
    exact_tokens.discard("")
    if normalized_selector in exact_tokens:
        return 2
    text_tokens = [token for token in exact_tokens if "." not in token or not re.fullmatch(r"\d+(?:\.\d+){3}", token)]
    if any(normalized_selector in token for token in text_tokens):
        return 1
    return 0


def describe_tailscale_peer(peer: TailscalePeer) -> str:
    labels = [peer.hostname or "(no hostname)"]
    if peer.dns_name:
        labels.append(peer.dns_name.rstrip("."))
    labels.append(peer.primary_ipv4() or "(no ipv4)")
    labels.append(peer.os or "unknown-os")
    labels.append("online" if peer.online else "offline")
    return " / ".join(labels)


def _candidate_peer_message(peers: list[TailscalePeer]) -> str:
    if not peers:
        return "(후보 없음)"
    return "\n".join(f"  - {describe_tailscale_peer(peer)}" for peer in peers)


def select_tailscale_peer(snapshot: TailscaleSnapshot, selector: str | None = None) -> TailscalePeer:
    peers_with_ip = [peer for peer in snapshot.peers if peer.primary_ipv4()]
    if selector:
        scored = [(tailscale_peer_match_score(peer, selector), peer) for peer in peers_with_ip]
        best_score = max((score for score, _peer in scored), default=0)
        matches = [peer for score, peer in scored if score == best_score and score > 0]
        if not matches:
            raise RuntimeError(
                f"Tailscale peer {selector!r}를 찾지 못했습니다. 후보:\n{_candidate_peer_message(peers_with_ip)}"
            )
        if len(matches) > 1:
            raise RuntimeError(
                f"Tailscale peer {selector!r}가 여러 기기와 매칭됩니다. 더 정확한 이름을 지정하세요:\n"
                f"{_candidate_peer_message(matches)}"
            )
        return matches[0]

    android_peers = [peer for peer in peers_with_ip if peer.os.lower() == "android"]
    if len(android_peers) == 1:
        return android_peers[0]
    if not android_peers:
        raise RuntimeError(
            "Tailscale status에서 Android IPv4 peer를 찾지 못했습니다. "
            "--tailscale-device 또는 --device-ip를 지정하세요. 후보:\n"
            f"{_candidate_peer_message(peers_with_ip)}"
        )
    raise RuntimeError(
        "Tailscale Android peer가 여러 개입니다. --tailscale-device 또는 "
        "HH_ANDROID_TAILSCALE_DEVICE로 특정하세요:\n"
        f"{_candidate_peer_message(android_peers)}"
    )


def resolve_tailscale_device_ip(selector: str | None = None) -> str:
    snapshot = tailscale_status(timeout_seconds=3.0, cache_ttl_seconds=0.0)
    if not snapshot.installed:
        raise RuntimeError(f"Tailscale CLI를 사용할 수 없습니다: {snapshot.message}")
    peer = select_tailscale_peer(snapshot, selector)
    device_ip = peer.primary_ipv4()
    if not device_ip:
        raise RuntimeError(f"Tailscale peer에 IPv4가 없습니다: {describe_tailscale_peer(peer)}")
    print(f"  ✓ Tailscale device: {describe_tailscale_peer(peer)}")
    return device_ip


def resolve_default_remote_base_url(host_url: str | None, host_tailscale_device: str | None) -> str:
    if host_url and host_tailscale_device:
        raise RuntimeError("--host-url과 --host-tailscale-device는 동시에 지정할 수 없습니다.")
    if host_url:
        return validate_remote_base_url_for_android(host_url)
    if not host_tailscale_device:
        return ""

    snapshot = tailscale_status(timeout_seconds=3.0, cache_ttl_seconds=0.0)
    if not snapshot.installed:
        raise RuntimeError(f"Tailscale CLI를 사용할 수 없습니다: {snapshot.message}")
    peer = select_tailscale_peer(snapshot, host_tailscale_device)
    host_ip = peer.primary_ipv4()
    if not host_ip:
        raise RuntimeError(f"Tailscale host peer에 IPv4가 없습니다: {describe_tailscale_peer(peer)}")
    base_url = validate_remote_base_url_for_android(host_ip)
    print(f"  ✓ Tailscale host: {describe_tailscale_peer(peer)} → {base_url}")
    return base_url


def prompt_port(label: str, current: int | None) -> int | None:
    if current is not None:
        return current
    if not sys.stdin.isatty():
        return None
    value = input(f"{label} 포트(건너뛰려면 Enter): ").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{label} 포트는 숫자여야 합니다: {value}") from exc


def adb_pair(adb: str, device_ip: str, pair_port: int, pair_code: str | None) -> None:
    command = [adb, "pair", f"{device_ip}:{pair_port}"]
    if pair_code:
        command.append(pair_code)
    elif not sys.stdin.isatty():
        raise RuntimeError("--pair-code 없이 non-interactive adb pair를 실행할 수 없습니다.")
    _run(command)


def adb_connect(adb: str, device_ip: str, connect_port: int) -> str:
    address = f"{device_ip}:{connect_port}"
    result = _run([adb, "connect", address], capture=True, check=True)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    return address


def prepare_wireless_adb(args: argparse.Namespace, adb: str) -> str:
    if args.serial and not args.device_ip and not args.tailscale_device:
        return args.serial
    if not args.device_ip:
        args.device_ip = resolve_tailscale_device_ip(args.tailscale_device)

    services = discover_mdns_services(adb)
    pair_port = args.pair_port or choose_mdns_port(services, ADB_TLS_PAIRING_SERVICE, args.device_ip)
    connect_port = args.connect_port or choose_mdns_port(services, ADB_TLS_CONNECT_SERVICE, args.device_ip)

    if not args.skip_pair:
        pair_port = prompt_port("Wireless debugging pairing", pair_port)
        if pair_port is not None:
            adb_pair(adb, args.device_ip, pair_port, args.pair_code)
        else:
            print("  (pair 포트가 없어 adb pair를 건너뜁니다. 이미 페어링된 기기라면 connect만 진행합니다.)")

    connect_port = prompt_port("Wireless debugging connect", connect_port)
    if connect_port is None:
        raise RuntimeError("adb connect 포트가 필요합니다. 휴대폰 Wireless debugging 화면의 IP:port 중 port를 전달하세요.")
    connected = adb_connect(adb, args.device_ip, connect_port)
    return args.serial or connected


def install_apk(adb: str, serial: str, apk: Path) -> None:
    _run([adb, "-s", serial, "install", "-r", str(apk)])


def launch_app(adb: str, serial: str) -> None:
    _run([adb, "-s", serial, "shell", "am", "start", "-n", MAIN_ACTIVITY])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and install the Android Remote client over wireless adb.")
    parser.add_argument("--device-ip", default=os.environ.get("HH_ANDROID_DEVICE_IP"), help="Stable device IP override. If omitted, the script resolves a Tailscale Android peer.")
    parser.add_argument("--tailscale-device", default=os.environ.get("HH_ANDROID_TAILSCALE_DEVICE"), help="Tailscale hostname/DNS name/node ID/IP selector. If omitted, exactly one Android peer is auto-selected.")
    parser.add_argument("--host-url", default=os.environ.get("HH_ANDROID_REMOTE_BASE_URL"), help="Remote Agent base URL or host/IP to seed into the Android app. Public URLs must be HTTPS; private bare host/IP becomes http://<host>:8000. Env: HH_ANDROID_REMOTE_BASE_URL.")
    parser.add_argument("--host-tailscale-device", default=os.environ.get("HH_ANDROID_HOST_TAILSCALE_DEVICE"), help="Tailscale hostname/DNS name/node ID/IP selector for the Remote Agent host. The resolved IP becomes http://<ip>:8000. Env: HH_ANDROID_HOST_TAILSCALE_DEVICE.")
    parser.add_argument("--pair-port", type=int, default=None, help="Port shown by 'Pair device with pairing code'.")
    parser.add_argument("--connect-port", type=int, default=None, help="Wireless debugging connect port.")
    parser.add_argument("--pair-code", default=None, help="Optional six-digit pairing code. If omitted, adb prompts interactively.")
    parser.add_argument("--skip-pair", action="store_true", help="Skip adb pair and only run adb connect/install.")
    parser.add_argument("--serial", default=None, help="Install serial override. If --device-ip is omitted, this skips wireless pair/connect.")
    parser.add_argument("--adb", default=None, help="adb executable path.")
    parser.add_argument("--version-file", type=Path, default=build.VERSION_CONFIG_FILE)
    parser.add_argument("--bump", choices=build.VERSION_BUMP_CHOICES, default=build.DEFAULT_VERSION_BUMP)
    parser.add_argument("--archive-keep", type=int, default=10)
    parser.add_argument("--archive-days", type=int, default=90)
    parser.add_argument("--no-prune-archives", action="store_true")
    parser.add_argument("--no-install", action="store_true", help="Build/copy/check the release APK but do not run adb pair/connect/install.")
    parser.add_argument(
        "--uninstall-on-signature-mismatch",
        action="store_true",
        help="If the installed package uses a different signing certificate, uninstall it before installing. This deletes app data.",
    )
    parser.add_argument("--launch", action="store_true", help="Launch the app after successful install.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = build.load_version_config(args.version_file)
        candidate_config = candidate_android_version_config(config, args.bump)
        version_info = build.make_version_info(ANDROID_TARGET, candidate_config)
        version_code = android_version_code(version_info)
        print("== Android Remote build ==")
        print(f"- version: {version_info['version']} (build {version_info['build']}, versionCode {version_code})")
        print(f"- release_id: {version_info['string']}")
        if version_info["dirty"]:
            print("- warning: 작업 트리에 커밋되지 않은 변경이 있어 release_id에 _dirty가 붙었습니다.")
        default_remote_base_url = resolve_default_remote_base_url(args.host_url, args.host_tailscale_device)
        if default_remote_base_url:
            print(f"- default Remote Agent URL: {default_remote_base_url}")

        print("\n== Archive old Android APKs ==")
        archived = archive_release_artifacts(
            targets={ANDROID_TARGET},
            archive_keep=args.archive_keep,
            archive_days=args.archive_days,
            prune_archives=not args.no_prune_archives,
        )
        if not archived:
            print("  (아카이빙할 Android APK 없음)")

        print("\n== Build APK ==")
        build_android_apk(version_info, default_remote_base_url=default_remote_base_url)
        release_apk = copy_release_apk(version_info)
        check_release_apk(release_apk, version_info)

        if args.no_install:
            build.save_version_config(candidate_config, args.version_file)
            print(f"  ✓ version saved: {args.version_file}")
            print("\n== Install skipped ==")
            return 0

        print("\n== Wireless adb install ==")
        adb = resolve_adb(args.adb)
        serial = prepare_wireless_adb(args, adb)
        preflight_install_signature(
            adb,
            serial,
            release_apk,
            uninstall_on_signature_mismatch=args.uninstall_on_signature_mismatch,
        )
        install_apk(adb, serial, release_apk)
        if args.launch:
            launch_app(adb, serial)
        build.save_version_config(candidate_config, args.version_file)
        print(f"  ✓ version saved: {args.version_file}")
        print("\nAndroid Remote APK build/install completed.")
        return 0
    except build.BuildConfigError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
