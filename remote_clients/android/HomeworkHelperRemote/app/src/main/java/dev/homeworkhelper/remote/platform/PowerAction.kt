package dev.homeworkhelper.remote.platform

enum class PowerAction(val wireName: String, val label: String) {
    Wake("wake", "깨우기"),
    Sleep("sleep", "절전"),
    Restart("restart", "재시작"),
    Shutdown("shutdown", "종료"),
}
