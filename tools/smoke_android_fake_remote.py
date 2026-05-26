#!/usr/bin/env python3
"""Install the Android client and smoke it against a fake Remote Agent via adb reverse."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from fake_android_remote_agent import FakeRemoteHandler, IMAGE_HITS, LAUNCHES, STOPS
from http.server import ThreadingHTTPServer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOT = PROJECT_ROOT / "remote_clients/android/HomeworkHelperRemote"
DEFAULT_APK = ANDROID_ROOT / "app/build/outputs/apk/debug/app-debug.apk"
PACKAGE = "dev.homeworkhelper.remote"
PREFS_PATH = f"/data/user/0/{PACKAGE}/shared_prefs/homeworkhelper.remote.preferences.xml"


def run(command: list[str], *, input_text: str | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(command), flush=True)
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=True,
    )


def adb(serial: str | None, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    command = ["adb"]
    if serial:
        command += ["-s", serial]
    command += args
    return run(command, **kwargs)


def start_fake_agent(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), FakeRemoteHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def seed_preferences(serial: str | None, port: int) -> None:
    prefs = f'''<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <string name="remote.base_url">http://127.0.0.1:{port}</string>
    <string name="remote.device_name">Device Smoke</string>
    <string name="remote.cached_processes_json">[]</string>
    <long name="remote.last_sync_millis" value="0" />
</map>
'''
    adb(serial, ["shell", "run-as", PACKAGE, "mkdir", "-p", f"/data/user/0/{PACKAGE}/shared_prefs"])
    adb(
        serial,
        ["shell", f"run-as {PACKAGE} /system/bin/sh -c 'cat > {PREFS_PATH}'"],
        input_text=prefs,
    )


def dump_ui(serial: str | None, name: str, artifacts: Path) -> str:
    remote_xml = f"/sdcard/{name}.xml"
    local_xml = artifacts / f"{name}.xml"
    local_png = artifacts / f"{name}.png"
    adb(serial, ["shell", "uiautomator", "dump", remote_xml], capture=True)
    adb(serial, ["pull", remote_xml, str(local_xml)], capture=True)
    command = ["adb"]
    if serial:
        command += ["-s", serial]
    command += ["exec-out", "screencap", "-p"]
    print("$ " + " ".join(command), flush=True)
    png = subprocess.run(command, stdout=subprocess.PIPE, check=True).stdout
    local_png.write_bytes(png)
    return local_xml.read_text(encoding="utf-8", errors="ignore")


def require_markers(xml: str, markers: list[str]) -> None:
    missing = [marker for marker in markers if marker not in xml]
    if missing:
        raise AssertionError(f"missing UI markers: {', '.join(missing)}")


def tap_first_launch(serial: str | None, xml: str) -> None:
    matches = re.findall(r'text="(?:▶ )?실행"[^>]*enabled="true"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if not matches:
        raise AssertionError("no enabled launch button text found")
    x1, y1, x2, y2 = map(int, matches[0])
    adb(serial, ["shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)])


def swipe_down(serial: str | None) -> None:
    adb(serial, ["shell", "input", "swipe", "500", "450", "500", "1200", "450"])


def tap_text(serial: str | None, xml: str, text: str) -> None:
    match = re.search(rf'text="{re.escape(text)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if not match:
        raise AssertionError(f"no text bounds found for {text}")
    x1, y1, x2, y2 = map(int, match.groups())
    adb(serial, ["shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2)])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=None, help="adb serial, e.g. 100.102.217.35:37667")
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--artifacts", type=Path, default=PROJECT_ROOT / "artifacts/android-device")
    args = parser.parse_args(argv)

    args.artifacts.mkdir(parents=True, exist_ok=True)
    server = start_fake_agent(args.port)
    try:
        adb(args.serial, ["reverse", f"tcp:{args.port}", f"tcp:{args.port}"])
        adb(args.serial, ["install", "-r", str(args.apk)])
        adb(args.serial, ["shell", "pm", "clear", PACKAGE])
        seed_preferences(args.serial, args.port)
        adb(args.serial, ["shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity"])
        time.sleep(1.5)

        home_xml = dump_ui(args.serial, "android-v3-home", args.artifacts)
        require_markers(home_xml, ["홈", "설정", "Fake Game A", "Fake Running Game", "실행", "online", "아래로 당겨 새로고침", "연결됨"])
        if "더보기" in home_xml:
            raise AssertionError("info-only More tab should not remain in bottom navigation")

        deadline = time.time() + 6
        while len(IMAGE_HITS) < 2 and time.time() < deadline:
            time.sleep(0.25)
        if len(IMAGE_HITS) < 2:
            raise AssertionError(f"fake PNG icon endpoints were not requested enough: {IMAGE_HITS}")

        swipe_down(args.serial)
        time.sleep(1.0)
        refreshed_xml = dump_ui(args.serial, "android-v3-pull-refresh", args.artifacts)
        require_markers(refreshed_xml, ["Fake Game A", "Fake Running Game", "등록된 게임"])

        tap_text(args.serial, refreshed_xml, "설정")
        time.sleep(0.5)
        setup_xml = dump_ui(args.serial, "android-v3-setup", args.artifacts)
        require_markers(setup_xml, ["연결/페어링", "Remote Agent URL", "기기 이름", "6자리 페어링 코드", "페어링", "Tailscale 기반환경", "전원", "기기", "앱"])
        tap_text(args.serial, setup_xml, "⚙ 앱")
        time.sleep(0.5)
        setup_more_xml = dump_ui(args.serial, "android-v3-setup-sections", args.artifacts)
        require_markers(setup_more_xml, ["앱 동작", "Tailscale", "Fake Remote Agent smoke", "launch/stop"])

        tap_text(args.serial, setup_more_xml, "홈")
        time.sleep(0.5)
        home_xml = dump_ui(args.serial, "android-v3-home-return", args.artifacts)
        tap_first_launch(args.serial, home_xml)
        time.sleep(1.0)
        launch_xml = dump_ui(args.serial, "android-v3-launch", args.artifacts)
        require_markers(launch_xml, ["Fake Game A 실행 요청을 접수했습니다.", "Fake Game A", "Fake Running Game", "연결됨"])
        if "fake-game-a" not in LAUNCHES:
            raise AssertionError("fake agent did not receive launch POST")
        tap_text(args.serial, launch_xml, "■ 중단")
        time.sleep(0.3)
        confirm_xml = dump_ui(args.serial, "android-v3-stop-confirm", args.artifacts)
        require_markers(confirm_xml, ["Fake Game A 중단", "중단", "취소"])
        tap_text(args.serial, confirm_xml, "중단")
        time.sleep(1.0)
        stop_xml = dump_ui(args.serial, "android-v3-stop", args.artifacts)
        require_markers(stop_xml, ["중단 요청을 접수했습니다.", "Fake Game A", "Fake Running Game", "연결됨"])
        if "fake-game-a" not in STOPS:
            raise AssertionError("fake agent did not receive stop POST")
        if not any("/api/dashboard/icons/" in hit for hit in IMAGE_HITS):
            raise AssertionError(f"process icon endpoint was not requested: {IMAGE_HITS}")
        if not any("/api/dashboard/resource-icons/" in hit for hit in IMAGE_HITS):
            raise AssertionError(f"resource icon endpoint was not requested: {IMAGE_HITS}")
        print("Android fake Remote Agent smoke passed.")
        return 0
    finally:
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
