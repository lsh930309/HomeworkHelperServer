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
    / "clients"
    / "macos"
    / "Sources"
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
    executable.write_text(
        """#!/bin/sh
case "$1:$2" in
  quit:fixture-success)
    printf 'fixture quit %s\\n' "$2"
    ;;
  quit:fixture-failure)
    printf 'fixture warning\\n' >&2
    exit 7
    ;;
  quit:fixture-verbose)
    i=0
    while [ "$i" -lt 4096 ]; do
      printf 'fixture diagnostic line %s on stdout\\n' "$i"
      printf 'fixture diagnostic line %s on stderr\\n' "$i" >&2
      i=$((i + 1))
    done
    ;;
  quit:fixture-inherited-output)
    /bin/sleep 7 &
    printf 'fixture helper exited\\n'
    ;;
  quit:fixture-timeout)
    trap '' TERM
    exec /bin/sleep 7
    ;;
  *) exit 64 ;;
esac
""",
        encoding="utf-8",
    )
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

        func testStreamEvidence(_ selected: LocalMoonlightSnapshot) {{
            let title = "LSH_Desktop"
            expect(selected.manualStreamWindowTitle == title, "the selected registration should supply its exact unique hostname")

            let target = selected.targetHost!
            func registration(hostname: String) -> LocalMoonlightHostCandidate {{
                LocalMoonlightHostCandidate(
                    uuid: "fixture-alternate", hostname: hostname,
                    localAddress: "", localPort: 0, manualAddress: "", manualPort: 0,
                    remoteAddress: "", remotePort: 0, ipv6Address: "", ipv6Port: 0,
                    apps: target.apps
                )
            }}
            func selectedTitle(_ host: LocalMoonlightHostCandidate, among hosts: [LocalMoonlightHostCandidate]) -> String? {{
                LocalMoonlightSnapshot(
                    installation: selected.installation, preferencesPath: selected.preferencesPath,
                    preferencesReadable: true, hosts: hosts, targetHost: host,
                    readiness: .ready, message: ""
                ).manualStreamWindowTitle
            }}
            let duplicate = registration(hostname: title)
            expect(selectedTitle(target, among: [target, duplicate]) == nil, "two registrations using the same title are ambiguous")
            let blank = registration(hostname: "   ")
            expect(selectedTitle(blank, among: [blank]) == nil, "a blank registration cannot match an untitled window")
            let launcher = registration(hostname: "Moonlight")
            expect(selectedTitle(launcher, among: [launcher]) == nil, "the generic launcher title cannot identify a host session")

            var titleReads: [pid_t] = []
            let matchingEvidence = LocalMoonlightManager.streamEvidence(
                for: [11, 22, 33, 44, 55, 66, 77, 99, 100, 101, 102], targetHostArgument: "HOST-2",
                manualStreamWindowTitle: selected.manualStreamWindowTitle,
                windowTitles: {{ pid in
                    titleReads.append(pid)
                    switch pid {{
                    case 11: return [title]
                    case 22: return ["Moonlight"]
                    case 33: return ["KDLPCWIN01"]
                    case 44: return [""]
                    case 55: return [title.lowercased(), "Moonlight – \\(title)"]
                    case 88: return [title]
                    default: return []
                    }}
                }},
                commandArguments: {{ pid in
                    switch pid {{
                    case 66: return "stream host-2 desktop"
                    case 77: return "stream HOST-1 Desktop"
                    case 99: return "stream HOST-20 Desktop"
                    case 100: return "stream HOST-2 NonDesktop"
                    case 101: return "quit HOST-2 Desktop"
                    case 102: return "stream HOST-2 Desktop --extra"
                    default: return ""
                    }}
                }}
            )
            expect(matchingEvidence == [11: .windowTitle, 66: .commandLine], "only an exact host and Desktop stream command or an exact manual window title can identify the session")
            expect(!titleReads.contains(66), "the matching CLI evidence should avoid consulting Accessibility")
            expect(!titleReads.contains(88), "a window outside the current running Moonlight PIDs must not be considered")

            let inactiveStream = LocalMoonlightSessionSnapshot(
                runningApplicationCount: 7, hasVisibleWindow: false, hasFocusedApplication: false,
                accessibilityTrusted: true, streamEvidenceByPID: matchingEvidence
            )
            expect(inactiveStream.hasDesktopSession && !inactiveStream.hasUnconfirmedSession, "window evidence should confirm the session outside the current visible space")
            expect(inactiveStream.streamProcessIDs == [11, 66], "both kinds of stream evidence should contribute their PID")
            let activeLauncher = LocalMoonlightSessionSnapshot(
                runningApplicationCount: 1, hasVisibleWindow: true, hasFocusedApplication: true,
                accessibilityTrusted: true, streamEvidenceByPID: [:]
            )
            expect(!activeLauncher.hasDesktopSession && activeLauncher.hasUnconfirmedSession, "a foreground launcher alone must not expose the OFF action")

            let noTitleEvidence = LocalMoonlightManager.streamEvidence(
                for: [11, 66], targetHostArgument: "HOST-2", manualStreamWindowTitle: nil,
                windowTitles: {{ _ in fatalError("Accessibility reader must not run without an eligible title") }},
                commandArguments: {{ $0 == 66 ? "stream HOST-2 Desktop" : "" }}
            )
            expect(noTitleEvidence == [66: .commandLine], "without eligible manual window evidence only the matching CLI stream is confirmed")
            let unselectedTargets: [String?] = [nil, "", "   "]
            for target in unselectedTargets {{
                let noTargetEvidence = LocalMoonlightManager.streamEvidence(
                    for: [66], targetHostArgument: target, manualStreamWindowTitle: nil,
                    windowTitles: {{ _ in fatalError("an unselected host cannot identify a manual window") }},
                    commandArguments: {{ _ in "stream HOST-2 Desktop" }}
                )
                expect(noTargetEvidence.isEmpty, "CLI arguments cannot confirm a stream without a selected host")
            }}
            let closedProcesses = LocalMoonlightManager.streamEvidence(
                for: [], targetHostArgument: "HOST-2", manualStreamWindowTitle: title,
                windowTitles: {{ _ in fatalError("a closed process must not be observed") }},
                commandArguments: {{ _ in fatalError("a closed process has no command arguments") }}
            )
            expect(closedProcesses.isEmpty, "manual evidence cannot survive after its process disappears")
        }}

        @main
        struct LocalMoonlightManagerSmoke {{
            static func main() async {{
                setenv("HH_REMOTE_MOONLIGHT_APP_PATHS", "{app_path}", 1)
                setenv("HH_REMOTE_MOONLIGHT_PREFS_PATH", "{plist_path}", 1)

                let ambiguous = LocalMoonlightManager.snapshot(baseURLHost: nil)
                expect(ambiguous.readiness == .needsTailscaleRegistration, "Moonlight registrations must not choose a host without HomeworkHelper identity")
                expect(ambiguous.hosts.count == 2, "fixture should expose two hosts")
                expect(ambiguous.usableHosts.count == 2, "both fixture hosts should expose Desktop")
                expect(ambiguous.manualStreamWindowTitle == nil, "an unselected host must not supply a manual stream title")

                let matched = LocalMoonlightManager.snapshot(baseURLHost: "172.30.1.34")
                expect(matched.readiness == .ready, "base URL host should select matching Moonlight host")
                expect(matched.targetHost?.uuid == "HOST-2", "base URL host should select HOST-2")
                expect(matched.targetHost?.targetHostArgument == "HOST-2", "future stream target should prefer Moonlight uuid")

                let matchedByName = LocalMoonlightManager.snapshot(baseURLHost: nil, hostNameHints: ["lsh-desktop"])
                expect(matchedByName.readiness == .ready, "hostname hint should select matching Moonlight host")
                expect(matchedByName.targetHost?.uuid == "HOST-2", "hostname hint should select HOST-2")

                let matchedByPublicIP = LocalMoonlightManager.snapshot(baseURLHost: nil, publicIPHints: ["211.216.28.65"])
                expect(matchedByPublicIP.readiness == .ready, "public IP hint should select matching Moonlight host")
                expect(matchedByPublicIP.targetHost?.uuid == "HOST-2", "public IP hint should select HOST-2")

                let needsRegistration = LocalMoonlightManager.snapshot(baseURLHost: nil, hostNameHints: ["homework-host"], publicIPHints: ["203.0.113.5"])
                expect(needsRegistration.readiness == .needsTailscaleRegistration, "identity hints without a matching Moonlight host should request Tailscale registration")
                expect(needsRegistration.targetHost == nil, "unmatched HomeworkHelper identity hints must not auto-select an unrelated Moonlight host")

                let stale = LocalMoonlightManager.snapshot(baseURLHost: "192.168.20.65", publicIPHints: ["211.216.28.65"])
                expect(!stale.stalePublicIPWarning.isEmpty, "selected host should warn when collected public IP differs from saved remote address")

                let selected = LocalMoonlightManager.snapshot(baseURLHost: "172.30.1.34")
                expect(selected.readiness == .ready, "HomeworkHelper address must own the stream target")
                expect(selected.targetHost?.uuid == "HOST-2", "HomeworkHelper address must select HOST-2")
                expect(selected.installation?.version == "6.1.0-fixture", "fake app version should be detected")
                testStreamEvidence(selected)

                let success = await LocalMoonlightManager.quit(host: "fixture-success", installation: selected.installation)
                expect(success.succeeded && success.stdout == "fixture quit fixture-success", "quit should pass the selected target and capture normal output")

                let failure = await LocalMoonlightManager.quit(host: "fixture-failure", installation: selected.installation)
                expect(!failure.succeeded && failure.exitStatus == 7 && !failure.timedOut && failure.stderr == "fixture warning", "quit should preserve helper failure and its diagnostic")

                let verbose = await LocalMoonlightManager.quit(host: "fixture-verbose", installation: selected.installation, timeoutSeconds: 3)
                expect(verbose.succeeded, "both stdout and stderr should be drained while the quit helper runs")

                let inheritedStart = ContinuousClock.now
                let inherited = await LocalMoonlightManager.quit(host: "fixture-inherited-output", installation: selected.installation)
                expect(inherited.succeeded && inherited.stdout == "fixture helper exited", "quit output should survive until its helper exits")
                expect(ContinuousClock.now - inheritedStart < .seconds(5), "quit must not wait for inherited output held by a separate process")

                let start = ContinuousClock.now
                let timeout = await LocalMoonlightManager.quit(host: "fixture-timeout", installation: selected.installation, timeoutSeconds: 1)
                expect(timeout.timedOut && !timeout.succeeded, "quit must report timeout when the fixture ignores normal termination")
                expect(ContinuousClock.now - start < .seconds(5), "quit must return before the stuck fixture exits on its own")

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
            "-module-cache-path",
            str(root / "swift-module-cache"),
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
        fixture_before = plist_path.read_bytes()
        run_result = subprocess.run([str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, check=False, timeout=20)
        if run_result.stdout:
            print(run_result.stdout, end="")
        if plist_path.read_bytes() != fixture_before:
            raise RuntimeError("Moonlight registration lookup modified its fixture")
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
