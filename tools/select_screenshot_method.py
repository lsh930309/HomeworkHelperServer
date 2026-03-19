"""
스크린샷 구현 방법 적용 스크립트
=================================

사용법:
  python tools/select_screenshot_method.py        # 진단 결과(_method.txt) 자동 읽기
  python tools/select_screenshot_method.py A      # Method A 직접 지정
  python tools/select_screenshot_method.py B      # Method B 직접 지정

수행 내용:
  1. 미사용 method 파일을 .bak으로 백업 (삭제 대신 보존)
  2. manager.py의 _ACTIVE_METHOD 상수를 채택된 방법으로 업데이트
  3. _method.txt 갱신
"""
import shutil
import sys
from pathlib import Path

ROOT          = Path(__file__).parent.parent
SCREENSHOT    = ROOT / "src" / "screenshot"
METHOD_FILE   = SCREENSHOT / "_method.txt"

METHOD_FILES = {
    "A": SCREENSHOT / "method_a.py",
    "B": SCREENSHOT / "method_b.py",
}
MANAGER_FILE = SCREENSHOT / "manager.py"


def apply_method(method: str) -> None:
    method = method.strip().upper()
    if method not in ("A", "B"):
        print(f"[오류] 잘못된 방법: '{method}'. A 또는 B를 입력하세요.")
        sys.exit(1)

    other = "B" if method == "A" else "A"
    keep_file   = METHOD_FILES[method]
    remove_file = METHOD_FILES[other]

    print(f"\nMethod {method} 적용 중...\n")

    # 1. 미사용 구현 파일 백업
    if remove_file.exists():
        bak = remove_file.with_suffix(".py.bak")
        shutil.copy2(str(remove_file), str(bak))
        remove_file.unlink()
        print(f"  미사용 구현 백업: {remove_file.name} → {bak.name}")
    else:
        bak = remove_file.with_suffix(".py.bak")
        if bak.exists():
            print(f"  미사용 구현 이미 백업됨: {bak.name}")

    if keep_file.exists():
        print(f"  채택 구현 유지:   {keep_file.name}")
    else:
        bak_restore = keep_file.with_suffix(".py.bak")
        if bak_restore.exists():
            shutil.copy2(str(bak_restore), str(keep_file))
            print(f"  채택 구현 복원:   {bak_restore.name} → {keep_file.name}")
        else:
            print(f"  [경고] {keep_file.name} 이 없습니다. 먼저 git checkout으로 복원하세요.")

    # 2. manager.py 업데이트
    if MANAGER_FILE.exists():
        content = MANAGER_FILE.read_text(encoding="utf-8")
        lines = []
        for line in content.splitlines():
            if line.startswith("_ACTIVE_METHOD"):
                lines.append(f'_ACTIVE_METHOD = "{method}"')
            else:
                lines.append(line)
        MANAGER_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"  manager.py 업데이트: _ACTIVE_METHOD = \"{method}\"")
    else:
        print("  [경고] manager.py 를 찾을 수 없습니다.")

    # 3. _method.txt 갱신
    METHOD_FILE.write_text(method, encoding="utf-8")
    print(f"  _method.txt 갱신: {method}")

    print(f"\n완료. Method {method} 이 활성화되었습니다.")
    print("  ※ 나중에 되돌리려면 .bak 파일을 .py 로 이름 변경 후 다시 이 스크립트를 실행하세요.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        method_arg = sys.argv[1]
    elif METHOD_FILE.exists():
        method_arg = METHOD_FILE.read_text(encoding="utf-8").strip()
        print(f"_method.txt 에서 읽음: Method {method_arg}")
    else:
        print("[오류] 방법을 지정하거나 먼저 진단 도구를 실행하세요:")
        print("  python tools/diagnose_gamepad_screenshot.py")
        sys.exit(1)

    apply_method(method_arg)
