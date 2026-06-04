#!/usr/bin/env python3
"""Smoke test LocalMoonlightManager against an isolated Moonlight plist fixture."""

from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOONLIGHT_MANAGER = (
    PROJECT_ROOT
    / "remote_clients"
    / "macos"
    / "HomeworkHelperRemote"
    / "Sources"
    / "HomeworkHelperRemote"
    / "LocalMoonlightManager.swift"
)


def _write_fake_moonlight_app(root: Path) -> Path:
    app = root / "Moonlight.app"
    contents = app / "Contents"
    executable_dir = contents / "MacOS"
    executable_dir.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "com.moonlight-stream.Moonlight",
                "CFBundleExecutable": "Moonlight",
                "CFBundleShortVersionString": "6.1.0-fixture",
            }
        )
    )
    executable = executable_dir / "Moonlight"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return app


def _write_fixture_plist(root: Path) -> Path:
    path = root / "com.moonlight-stream.Moonlight.plist"
    payload = {
        "hosts.size": 2,
        "hosts.1.hostname": "KDLPCWIN01",
        "hosts.1.uuid": "HOST-1",
        "hosts.1.localaddress": "192.168.20.65",
        "hosts.1.localport": 47989,
        "hosts.1.remoteaddress": "14.63.27.145",
        "hosts.1.remoteport": 47989,
        "hosts.1.mac": b"secret-mac-bytes",
        "hosts.1.srvcert": b"secret-cert-bytes",
        "hosts.1.apps.size": 2,
        "hosts.1.apps.1.name": "Desktop",
        "hosts.1.apps.1.id": 881448767,
        "hosts.1.apps.1.hidden": False,
        "hosts.1.apps.2.name": "Virtual Display",
        "hosts.1.apps.2.id": 382300562,
        "hosts.2.hostname": "LSH_Desktop",
        "hosts.2.uuid": "HOST-2",
        "hosts.2.localaddress": "172.30.1.34",
        "hosts.2.localport": 47989,
        "hosts.2.manualaddress": "211.216.28.65",
        "hosts.2.manualport": 47989,
        "hosts.2.apps.size": 1,
        "hosts.2.apps.1.name": "Desktop",
        "hosts.2.apps.1.id": 881448767,
    }
    path.write_bytes(plistlib.dumps(payload))
    return path


def _swift_source(app_path: Path, plist_path: Path) -> str:
    return textwrap.dedent(
        f"""
        import Foundation

        func expect(_ condition: @autoclosure () -> Bool, _ message: String) {{
            if !condition() {{
                fatalError(message)
            }}
        }}

        @main
        struct LocalMoonlightManagerSmoke {{
            static func main() {{
                setenv("HH_REMOTE_MOONLIGHT_APP_PATHS", "{app_path}", 1)
                setenv("HH_REMOTE_MOONLIGHT_PREFS_PATH", "{plist_path}", 1)

                let ambiguous = LocalMoonlightManager.snapshot(selectedHostUUID: "", baseURLHost: nil)
                expect(ambiguous.readiness == .ambiguous, "two Desktop hosts without a base URL match should be ambiguous")
                expect(ambiguous.hosts.count == 2, "fixture should expose two hosts")
                expect(ambiguous.usableHosts.count == 2, "both fixture hosts should expose Desktop")

                let matched = LocalMoonlightManager.snapshot(selectedHostUUID: "", baseURLHost: "172.30.1.34")
                expect(matched.readiness == .ready, "base URL host should select matching Moonlight host")
                expect(matched.targetHost?.uuid == "HOST-2", "base URL host should select HOST-2")
                expect(matched.targetHost?.targetHostArgument == "HOST-2", "future stream target should prefer Moonlight uuid")

                let matchedByName = LocalMoonlightManager.snapshot(selectedHostUUID: "", baseURLHost: nil, hostNameHints: ["lsh-desktop"])
                expect(matchedByName.readiness == .ready, "hostname hint should select matching Moonlight host")
                expect(matchedByName.targetHost?.uuid == "HOST-2", "hostname hint should select HOST-2")

                let matchedByPublicIP = LocalMoonlightManager.snapshot(selectedHostUUID: "", baseURLHost: nil, publicIPHints: ["211.216.28.65"])
                expect(matchedByPublicIP.readiness == .ready, "public IP hint should select matching Moonlight host")
                expect(matchedByPublicIP.targetHost?.uuid == "HOST-2", "public IP hint should select HOST-2")

                let needsRegistration = LocalMoonlightManager.snapshot(selectedHostUUID: "", baseURLHost: nil, hostNameHints: ["homework-host"], publicIPHints: ["203.0.113.5"])
                expect(needsRegistration.readiness == .needsManualHostRegistration, "identity hints without a matching Moonlight host should request manual host registration")
                expect(needsRegistration.targetHost == nil, "unmatched HomeworkHelper identity hints must not auto-select an unrelated Moonlight host")

                let stale = LocalMoonlightManager.snapshot(selectedHostUUID: "HOST-1", baseURLHost: nil, publicIPHints: ["211.216.28.65"])
                expect(!stale.stalePublicIPWarning.isEmpty, "selected host should warn when collected public IP differs from saved remote address")

                let selected = LocalMoonlightManager.snapshot(selectedHostUUID: "HOST-1", baseURLHost: "172.30.1.34")
                expect(selected.readiness == .ready, "stored host selection should override auto-match")
                expect(selected.targetHost?.uuid == "HOST-1", "stored host selection should select HOST-1")
                expect(selected.installation?.version == "6.1.0-fixture", "fake app version should be detected")

                print("LocalMoonlightManager smoke passed: hosts=\\(selected.hosts.count), target=\\(selected.targetHost?.displayTitle ?? "-")")
            }}
        }}
        """
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hh-moonlight-smoke-") as temp:
        root = Path(temp)
        app_path = _write_fake_moonlight_app(root)
        plist_path = _write_fixture_plist(root)
        smoke_source = root / "LocalMoonlightManagerSmoke.swift"
        binary = root / "LocalMoonlightManagerSmoke"
        smoke_source.write_text(_swift_source(app_path, plist_path), encoding="utf-8")
        compile_cmd = [
            "swiftc",
            "-parse-as-library",
            str(MOONLIGHT_MANAGER),
            str(smoke_source),
            "-o",
            str(binary),
        ]
        compile_result = subprocess.run(compile_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if compile_result.returncode != 0:
            print(compile_result.stdout, file=sys.stderr)
            return compile_result.returncode
        env = os.environ.copy()
        run_result = subprocess.run([str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, check=False)
        if run_result.stdout:
            print(run_result.stdout, end="")
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
