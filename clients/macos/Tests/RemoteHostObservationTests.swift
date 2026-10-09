import XCTest
@testable import HomeworkHelperRemote

final class RemoteHostObservationTests: XCTestCase {
    private func identity(host: String = "desktop", token: String = "stored-token") -> RemoteHostIdentity {
        RemoteHostIdentity(baseURL: "http://\(host):8000", moonlightHostUUID: "host-id", token: token,
            sshHost: host, sshUser: "owner", sshKeyPath: "/fixture/key", sshPort: 22)
    }

    func testLoginScreenStreamingDoesNotRequireAppOrAppAuthentication() {
        for app in [RemoteAppObservation.waiting, .authRejected, .notPaired] {
            let observed = RemoteHostObservationSnapshot(pc: .reachable, apollo: .ready, app: app, sshPowerReady: true)
            XCTAssertTrue(observed.canStream)
            XCTAssertFalse(observed.appReady)
            XCTAssertFalse(observed.shouldWake)
            XCTAssertTrue(observed.sshPowerReady)
            XCTAssertEqual(observed.label(), app == .authRejected ? "인증 확인 필요" : "호스트 대기")
        }
    }

    func testPCReachabilityPreventsWakeEvenWhenApolloAndAppAreUnavailable() {
        let observed = RemoteHostObservationSnapshot(pc: .reachable, apollo: .unavailable, app: .waiting)
        XCTAssertFalse(observed.shouldWake)
        XCTAssertFalse(observed.canStream)
        XCTAssertEqual(observed.label(), "스트리밍 대기")
    }

    func testUnavailablePingCannotDeclareThePCOffOrTriggerWake() {
        let observed = RemoteHostObservationSnapshot(pc: .unavailable, apollo: .unavailable, app: .waiting)
        XCTAssertFalse(observed.shouldWake)
        XCTAssertEqual(observed.label(), "Tailscale 오류")
    }

    func testAcceptedPowerIntentIsAnExpectationNotPhysicalOffProof() {
        let observed = RemoteHostObservationSnapshot(pc: .unreachable, apollo: .unavailable, app: .waiting)
        XCTAssertTrue(observed.shouldWake)
        XCTAssertEqual(observed.label(), "호스트 응답 없음")
        XCTAssertEqual(observed.label(availability: .goingOffline), "종료 대기 중")
    }

    func testExistingStatusLabelsAndAdditionalPreloginStates() {
        let ready = RemoteHostObservationSnapshot(pc: .reachable, apollo: .ready, app: .ready)
        XCTAssertEqual(ready.label(), "페어링됨")
        XCTAssertEqual(ready.label(isSyncing: true), "동기화 중")
        XCTAssertEqual(ready.label(isPaired: false), "페어링 해제됨")
        let waiting = RemoteHostObservationSnapshot(pc: .reachable, apollo: .ready, app: .waiting)
        XCTAssertEqual(waiting.label(), "호스트 대기")
        for state in [RemoteHostAvailabilityState.goingOffline, .waking, .restarting, .reconnecting, .authRejected] {
            XCTAssertEqual(waiting.label(availability: state), state.label)
        }
        XCTAssertEqual(RemoteHostObservationSnapshot().label(), "상태 확인 중")
        XCTAssertEqual(RemoteHostObservationSnapshot().label(availability: .agentUnavailable), "서버 응답 없음")
        XCTAssertEqual(RemoteHostObservationSnapshot(pc: .unreachable).label(availability: .offlineExpected), "호스트 응답 없음")
        XCTAssertEqual(RemoteHostObservationSnapshot(pc: .reachable, apollo: .identityMismatch).label(), "스트리밍 대기")
    }

    func testChangingHostRejectsItsLateResponsesAndClearsPowerCapability() {
        var store = RemoteHostObservationStore()
        let request = store.begin(for: identity())
        let ready = RemoteHostObservationSnapshot(pc: .reachable, apollo: .ready, app: .ready, sshPowerReady: true)
        store.reset(to: identity(host: "another"))
        XCTAssertFalse(store.accept(ready, for: request))
        XCTAssertFalse(store.snapshot.canStream)
        XCTAssertFalse(store.snapshot.sshPowerReady)
    }

    func testNewestRequestWinsWhenReceiptsArriveInReverseOrder() {
        var store = RemoteHostObservationStore()
        let old = store.begin(for: identity())
        let fresh = store.begin(for: identity())
        let freshSnapshot = RemoteHostObservationSnapshot(pc: .unreachable, apollo: .unavailable, app: .waiting)
        XCTAssertTrue(store.accept(freshSnapshot, for: fresh))
        XCTAssertFalse(store.accept(RemoteHostObservationSnapshot(pc: .reachable, apollo: .ready, app: .ready), for: old))
        XCTAssertEqual(store.snapshot, freshSnapshot)
    }

    func testCredentialChangesInvalidatePendingAuthenticatedResponse() {
        var store = RemoteHostObservationStore()
        let request = store.begin(for: identity())
        store.reset(to: identity(token: "replacement"))
        XCTAssertFalse(store.accept(RemoteHostObservationSnapshot(app: .ready), for: request))
    }

    func testObservationCadenceContinuesWhenAppIsAbsent() {
        XCTAssertEqual(RemoteHostObservationStore.pollDelaySeconds(screenVisible: true), 5)
        XCTAssertEqual(RemoteHostObservationStore.pollDelaySeconds(screenVisible: false), 15)
        XCTAssertEqual(RemoteHostObservationStore.pollDelaySeconds(screenVisible: true, userBaseIntervalSeconds: 12), 12)
        XCTAssertEqual(RemoteHostObservationStore.pollDelaySeconds(screenVisible: false, userBaseIntervalSeconds: 60), 15)
    }

    func testAnonymousPairStatusIsNotAPairingOrReadinessRequirement() {
        let xml = #"<root status_code="200"><uniqueid>HOST-ID</uniqueid><PairStatus>0</PairStatus></root>"#
        XCTAssertEqual(RemoteApolloProbe.decodeServerInfo(Data(xml.utf8), expectedUUID: "host-id"), .ready)
    }

    func testDifferentMoonlightIdentityCannotLaunchAnotherHost() {
        let xml = #"<root status_code="200"><uniqueid>other-host</uniqueid><PairStatus>1</PairStatus></root>"#
        XCTAssertEqual(RemoteApolloProbe.decodeServerInfo(Data(xml.utf8), expectedUUID: "host-id"), .identityMismatch)
        XCTAssertFalse(RemoteHostObservationSnapshot(pc: .reachable, apollo: .identityMismatch).canStream)
    }

    func testMalformedOrRejectedServerInfoCannotShowStreamingReady() {
        for xml in ["<html>other webserver</html>", #"<root status_code="401"><uniqueid>host-id</uniqueid></root>"#, "<root>"] {
            XCTAssertEqual(RemoteApolloProbe.decodeServerInfo(Data(xml.utf8), expectedUUID: "host-id"), .unavailable)
        }
    }

    func testSSHRequiresTheServiceCapabilityAndMatchingPowerAcceptance() throws {
        let ready = LocalSSHPowerManager.serviceResponse(from: #"{"accepted":true,"status":"ready","capabilities":["status","power"]}"#)
        XCTAssertTrue(ready?.readyForPower == true)
        XCTAssertFalse(LocalSSHPowerManager.serviceResponse(from: #"{"accepted":true,"status":"ready","capabilities":["status"]}"#)?.readyForPower == true)
        let accepted = LocalSSHPowerManager.serviceResponse(from: #"{"accepted":true,"status":"accepted","action":"sleep"}"#)
        XCTAssertTrue(accepted?.acceptsPower(action: "sleep") == true)
        XCTAssertFalse(accepted?.acceptsPower(action: "shutdown") == true)
        XCTAssertThrowsError(try LocalSSHPowerManager.command(for: "sleep; shutdown"))
    }
    func testProcessCacheCannotMoveBetweenHostsOrAPIPorts() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let previous = ProcessInfo.processInfo.environment["HH_REMOTE_CACHE_DIR"]
        setenv("HH_REMOTE_CACHE_DIR", directory.path, 1)
        defer {
            if let previous { setenv("HH_REMOTE_CACHE_DIR", previous, 1) }
            else { unsetenv("HH_REMOTE_CACHE_DIR") }
            try? FileManager.default.removeItem(at: directory)
        }
        let one = URL(string: "http://desktop:8000")!
        let another = URL(string: "http://other:8000")!
        let anotherPort = URL(string: "http://desktop:9000")!
        let process = try JSONDecoder().decode(RemoteProcess.self, from: Data(#"{"id":"game","name":"Host One Game"}"#.utf8))
        RemoteClientCache.saveProcesses([process], baseURL: one)
        XCTAssertEqual(RemoteClientCache.loadProcesses(baseURL: one).map(\.name), ["Host One Game"])
        XCTAssertTrue(RemoteClientCache.loadProcesses(baseURL: another).isEmpty)
        XCTAssertTrue(RemoteClientCache.loadProcesses(baseURL: anotherPort).isEmpty)
        XCTAssertTrue(RemoteClientCache.loadProcesses(baseURL: nil).isEmpty)
    }

}
