#!/usr/bin/env python3
"""Smoke test the macOS Remote connection supervisor as pure Swift logic."""

from __future__ import annotations

import subprocess
import tempfile
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR = PROJECT_ROOT / "remote_clients" / "macos" / "HomeworkHelperRemote" / "Sources" / "HomeworkHelperRemote" / "RemoteConnectionSupervisor.swift"


def _swift_source() -> str:
    return textwrap.dedent(
        r'''
        import Foundation

        func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
            if !condition() { fatalError(message) }
        }

        func decision(
            _ event: RemoteConnectionEvent,
            state: RemoteHostAvailabilityState,
            empty: Bool = true
        ) -> RemoteConnectionDecision {
            RemoteConnectionSupervisor.decide(event: event, currentState: state, reconnectScheduleIsEmpty: empty)
        }

        @main
        struct MacOSConnectionSupervisorSmoke {
            static func main() {
                let noReply = decision(.tailscaleReachability(result: .unreachable("no reply")), state: .online)
                expect(noReply.availabilityState == .offlineExpected, "tailscale no reply should infer offline host")
                expect(noReply.shouldLoadCache && noReply.shouldRefreshLocalProgress, "offline host should preserve standalone cache")
                expect(noReply.reconnectSchedule == [], "offline host should settle into standalone cadence instead of wake reconnect burst")

                let agentDownStart = decision(.httpStatusFailed(kind: .cannotConnect), state: .online)
                expect(agentDownStart.availabilityState == .reconnecting, "first HTTP connection loss should enter reconnecting")
                expect(agentDownStart.reconnectSchedule == RemoteConnectionSupervisor.connectionLossReconnectSchedule, "connection loss should use short reconnect burst")

                let layeredAgentDown = decision(.httpAgentUnavailable(kind: .cannotConnect, detail: "tailscale ping OK"), state: .online)
                expect(layeredAgentDown.availabilityState == .agentUnavailable, "HTTP failure with management reachability should become agentUnavailable immediately")
                expect(layeredAgentDown.reconnectSchedule == [], "layered agent unavailable should not run a blind reconnect burst")

                let agentDownExhausted = decision(.httpStatusFailed(kind: .cannotConnect), state: .reconnecting, empty: true)
                expect(agentDownExhausted.availabilityState == .agentUnavailable, "exhausted HTTP reconnect should become agentUnavailable")

                let auth = decision(.httpStatusFailed(kind: .authRejected), state: .online)
                expect(auth.availabilityState == .authRejected, "401/403 should become authRejected")
                expect(auth.reconnectSchedule == [], "authRejected should clear reconnect schedule")

                let wake = decision(.powerIntentAccepted(action: "wake"), state: .offlineExpected)
                expect(wake.availabilityState == .waking, "wake intent should enter waking")
                expect(wake.reconnectSchedule == RemoteConnectionSupervisor.wakeReconnectSchedule, "wake should use wake schedule")

                let sleep = decision(.powerIntentAccepted(action: "sleep"), state: .online)
                expect(sleep.availabilityState == .goingOffline, "sleep intent should enter goingOffline")
                expect(sleep.reconnectSchedule == RemoteConnectionSupervisor.expectedOfflineProbeSchedule, "sleep should use expected offline schedule")

                let staleGoingOffline = decision(.httpStatusSucceeded(powerHint: "on", stateRevision: "same"), state: .goingOffline)
                expect(staleGoingOffline.availabilityState == .goingOffline, "status success during goingOffline should not recover to online")
                expect(staleGoingOffline.reconnectSchedule == nil, "goingOffline status success should preserve existing schedule")
                expect(staleGoingOffline.shouldForcePayloadSync == false, "goingOffline status success should not force payload sync")

                let restart = decision(.powerIntentAccepted(action: "restart"), state: .online)
                expect(restart.availabilityState == .restarting, "restart intent should enter restarting")
                expect(restart.reconnectSchedule == RemoteConnectionSupervisor.restartReconnectSchedule, "restart should use restart schedule")

                let recovered = decision(.httpStatusSucceeded(powerHint: "ready", stateRevision: "same"), state: .offlineExpected)
                expect(recovered.availabilityState == .online, "status success should recover to online")
                expect(recovered.shouldForcePayloadSync, "disconnected recovery should force payload sync")

                let powerHintOff = decision(.httpStatusSucceeded(powerHint: "sleeping", stateRevision: "r1"), state: .online)
                expect(powerHintOff.availabilityState == .offlineExpected, "sleeping power hint should lower to offlineExpected")

                let resume = decision(.clientResumed, state: .offlineExpected)
                expect(resume.shouldRefreshLocalProgress, "client resume should refresh local progress")
                expect(resume.shouldProbeImmediately, "client resume should request immediate probe")

                print("macOS RemoteConnectionSupervisor smoke passed")
            }
        }
        '''
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hh-macos-connection-supervisor-") as temp_root:
        temp_dir = Path(temp_root)
        smoke = temp_dir / "MacOSConnectionSupervisorSmoke.swift"
        binary = temp_dir / "macos-connection-supervisor-smoke"
        smoke.write_text(_swift_source(), encoding="utf-8")
        compile_result = subprocess.run(
            ["swiftc", "-parse-as-library", str(SUPERVISOR), str(smoke), "-o", str(binary)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if compile_result.returncode != 0:
            print(f"macOS RemoteConnectionSupervisor smoke failed: swiftc exited {compile_result.returncode}\n{compile_result.stdout}")
            return 1
        run_result = subprocess.run([str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        print(run_result.stdout.strip())
        return run_result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
