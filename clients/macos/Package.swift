// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "HomeworkHelperRemote",
    platforms: [.macOS("26.0")],
    targets: [
        .executableTarget(
            name: "HomeworkHelperRemote",
            path: "Sources"
        )
    ]
)
