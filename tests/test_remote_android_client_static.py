from pathlib import Path
import xml.etree.ElementTree as ET


ANDROID_ROOT = Path("remote_clients/android/HomeworkHelperRemote")
MAIN_SRC = ANDROID_ROOT / "app/src/main/java/dev/homeworkhelper/remote"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _android_sources() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in MAIN_SRC.rglob("*.kt"))


def test_android_project_is_rebuild_scaffold_with_reproducible_compose_build():
    assert (ANDROID_ROOT / "settings.gradle.kts").exists()
    assert (ANDROID_ROOT / "gradlew").exists()
    assert (ANDROID_ROOT / "gradle/wrapper/gradle-wrapper.jar").exists()

    root_build = _read(ANDROID_ROOT / "build.gradle.kts")
    app_build = _read(ANDROID_ROOT / "app/build.gradle.kts")
    wrapper = _read(ANDROID_ROOT / "gradle/wrapper/gradle-wrapper.properties")

    assert 'id("com.android.application") version "8.13.0" apply false' in root_build
    assert 'id("org.jetbrains.kotlin.android") version "2.2.21" apply false' in root_build
    assert 'id("org.jetbrains.kotlin.plugin.compose") version "2.2.21" apply false' in root_build
    assert 'implementation(platform("androidx.compose:compose-bom:2026.03.00"))' in app_build
    assert 'implementation("androidx.activity:activity-compose:1.12.0")' in app_build
    assert 'implementation("androidx.compose.material3:material3")' in app_build
    assert "gradle-9.5.0-bin.zip" in wrapper

    assert (MAIN_SRC / "MainActivity.kt").exists()
    for legacy_file in [
        "RemoteAppViewModel.kt",
        "RemoteRepository.kt",
        "RemoteApiClient.kt",
        "RemoteModels.kt",
        "AndroidTokenStore.kt",
        "RemotePreferences.kt",
        "AndroidIntegration.kt",
        "ui/RemoteScreens.kt",
    ]:
        assert not (MAIN_SRC / legacy_file).exists()


def test_android_manifest_preserves_package_permissions_and_launcher_contract():
    manifest_path = ANDROID_ROOT / "app/src/main/AndroidManifest.xml"
    ET.parse(manifest_path)
    manifest = _read(manifest_path)

    assert 'android.permission.INTERNET' in manifest
    assert 'android.permission.PACKAGE_USAGE_STATS' in manifest
    assert 'tools:ignore="ProtectedPermissions"' in manifest
    assert 'android.intent.action.MAIN' in manifest
    assert 'android.intent.category.LAUNCHER' in manifest
    assert 'android:usesCleartextTraffic="true"' in manifest
    assert 'android:name=".MainActivity"' in manifest
    assert 'android:label="HomeworkHelper Remote"' in manifest


def test_android_scaffold_declares_rebuild_pending_instead_of_legacy_feature_surface():
    sources = _android_sources()

    assert "HomeworkHelperRemoteRebuildScaffold" in sources
    assert "Android rebuild scaffold" in sources
    assert "등록된 게임 현황과 빠른 실행" in sources
    assert "docs/remote/macos-client-architecture.md" in sources
    assert "docs/remote/android-client-design.md" in sources
    assert "REMOTE_CONNECTION_SUPERVISOR.md" in sources

    for stale in [
        "RemoteAppViewModel",
        "RemoteApiClient",
        "RemoteRepository",
        "RemoteScreens",
        "remote/power/config",
        "remote/power/smartthings/devices",
        "Full-parity",
        "Tailscale-first Android client",
        "Android-PC 연결 저장",
    ]:
        assert stale not in sources


def test_remote_docs_define_macos_reference_android_rebuild_and_shared_supervisor():
    macos = _read(Path("docs/remote/macos-client-architecture.md"))
    android = _read(Path("docs/remote/android-client-design.md"))
    supervisor = _read(Path("REMOTE_CONNECTION_SUPERVISOR.md"))
    setup = _read(Path("docs/remote/setup-guide.md"))
    android_readme = _read(ANDROID_ROOT / "README.md")
    root_readme = _read(Path("README.md"))

    for marker in [
        "macOS Remote Client Architecture",
        "menu-bar popover",
        "Android implication",
        "RemoteConnectionSupervisor",
        "The host does not expose `/remote/power/{action}`",
        "tools/smoke_macos_remote_viewmodel.py",
    ]:
        assert marker in macos

    for marker in [
        "Android Remote Client Rebuild Design",
        "The Android home screen is the equivalent of the macOS popover",
        "Home / Games",
        "Discard before rebuilding",
        "Do not use:",
        "/remote/power/config",
        "/remote/power/{action}",
        "process icon URLs",
    ]:
        assert marker in android

    for marker in [
        "Remote Connection Supervisor, Pairing, and Power Protocol",
        "OpenSSH automation protocol",
        "SSH command acceptance",
        "__HH_REMOTE_POWER_ACCEPTED__",
        "Android: keep power actions disabled",
        "The supervisor never parses raw SSH stdout/stderr",
    ]:
        assert marker in supervisor

    for marker in [
        "Android client rebuild scaffold",
        "docs/remote/macos-client-architecture.md",
        "docs/remote/android-client-design.md",
        "REMOTE_CONNECTION_SUPERVISOR.md",
        "The previous physical-device Android verifier is not a release gate",
    ]:
        assert marker in setup

    for marker in [
        "rebuild scaffold only",
        "Do not resurrect the deleted Android full-parity code",
        "macOS popover",
    ]:
        assert marker in android_readme

    assert "docs/remote/macos-client-architecture.md" in root_readme
    assert "docs/remote/android-client-design.md" in root_readme
    assert "REMOTE_CONNECTION_SUPERVISOR.md" in root_readme


def test_legacy_android_completion_docs_and_claims_are_removed():
    assert not Path("ANDROID_CLIENT_DEVICE_QA_REPORT.md").exists()

    checked_text = "\n".join(
        _read(path)
        for path in [
            Path("README.md"),
            Path("docs/remote/setup-guide.md"),
            Path("docs/remote/android-client-design.md"),
            ANDROID_ROOT / "README.md",
        ]
    )
    for stale in [
        "implemented Android rebuild baseline",
        "Current Android baseline:",
        "full-parity target and implementation sequence",
        "Full-parity 설계를 따라",
        "Android physical-device verification passed",
        "실기기 개선/검증 보고서",
    ]:
        assert stale not in checked_text


def test_android_internal_verifier_remains_scaffold_build_entrypoint():
    internal = _read(Path("tools/verify_android_internal.py"))
    artifact = _read(Path("tools/check_android_apk_artifact.py"))

    for marker in [
        "tests/test_remote_android_client_static.py",
        "tools/check_android_sdk_readiness.py",
        ":app:assembleDebug",
        "tools/check_android_apk_artifact.py",
        "Android internal verification passed",
    ]:
        assert marker in internal

    for marker in [
        "dev.homeworkhelper.remote",
        "android.permission.INTERNET",
        "android.permission.PACKAGE_USAGE_STATS",
        "Android APK artifact passed",
    ]:
        assert marker in artifact
